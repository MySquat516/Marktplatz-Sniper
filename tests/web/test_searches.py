from datetime import timedelta

from sniper.db import Search, Seen, set_setting
from sniper.models import Platform
from tests.engine.helpers import make_search, make_target
from tests.web.conftest import EBAY_URL, KA_URL, NOW, post


def test_root_redirects_to_searches(client):
    assert client.get("/").headers["Location"].endswith("/suchen")


def test_add_search_flow(client, session):
    t = make_target(session)
    session.commit()
    page = post(client, "/suchen/neu", url=KA_URL).get_data(as_text=True)
    assert "Carhartt Jacke Gr. L" in page  # Vorschau
    assert 'value="jacke"' in page  # Namensvorschlag
    post(
        client,
        "/suchen",
        url=KA_URL,
        name="Jacken",
        interval_min="5",
        max_price="60",
        exclude_words="defekt",
        silence_days="7",
        target_ids=str(t.id),
    )
    s = session.query(Search).one()
    assert (s.name, s.platform, s.interval_s, s.exclude_words) == (
        "Jacken",
        "kleinanzeigen",
        300,
        "defekt",
    )
    assert s.url == "https://www.kleinanzeigen.de/s-sortierung:neueste/jacke/k0"
    assert str(s.max_price) == "60.00"
    assert s.next_check_at == NOW
    assert [x.id for x in s.targets] == [t.id]


def test_listing_shows_state_labels(client, session):
    make_search(session, "Geblockte Suche", state="blocked")
    session.commit()
    page = client.get("/suchen").get_data(as_text=True)
    assert "Geblockte Suche" in page and "Geblockt" in page


def test_interval_minimum(client, session):
    page = post(client, "/suchen", url=KA_URL, name="x", interval_min="1", silence_days="7")
    assert "mindestens 2 Minuten" in page.get_data(as_text=True)
    assert session.query(Search).count() == 0


def test_add_unknown_url_shows_error(client):
    page = post(client, "/suchen/neu", url="https://example.com").get_data(as_text=True)
    assert "Unbekannte Seite" in page


def test_ignored_params_are_shown(make_app, session):
    from tests.web.conftest import logged_in

    client = logged_in(make_app(env_ebay=True))
    page = post(client, "/suchen/neu", url=EBAY_URL + "&LH_Sold=1").get_data(as_text=True)
    assert "Wird ignoriert: LH_Sold" in page


def test_preview_error_does_not_block_form(client):
    page = post(
        client, "/suchen/neu", url="https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz"
    ).get_data(as_text=True)
    assert "Vorschau nicht möglich" in page
    assert 'name="interval_min"' in page


def test_ebay_requires_credentials(client, session):
    page = post(client, "/suchen", url=EBAY_URL, name="x", interval_min="5", silence_days="7")
    assert "Erst eBay-Zugangsdaten in den Einstellungen eintragen." in page.get_data(as_text=True)
    assert session.query(Search).count() == 0


def test_ebay_credentials_from_settings_page_count(client, session):
    set_setting(session, "ebay_client_id", "id")
    set_setting(session, "ebay_client_secret", "sec")
    session.commit()
    post(client, "/suchen", url=EBAY_URL, name="x", interval_min="5", silence_days="7")
    assert session.query(Search).count() == 1


def test_ebay_quota_guard(make_app, session):
    from tests.web.conftest import logged_in

    for i in range(6):
        make_search(session, f"e{i}", platform=Platform.EBAY, interval_s=120)
    session.commit()
    client = logged_in(make_app(env_ebay=True))
    page = post(client, "/suchen", url=EBAY_URL, name="neu", interval_min="2", silence_days="7")
    text = page.get_data(as_text=True)
    assert "Zu viele eBay-Abfragen: hochgerechnet 5040 pro Tag, erlaubt sind 4500." in text
    assert session.query(Search).count() == 6


def test_edit_without_url_change_keeps_history(client, session):
    s = make_search(session, last_ok_at=NOW)
    s.url = "https://www.kleinanzeigen.de/s-sortierung:neueste/jacke/k0"
    session.add(
        Seen(
            search_id=s.id,
            platform="kleinanzeigen",
            external_id="1",
            status="seeded",
            listing_json="{}",
            first_seen_at=NOW,
        )
    )
    session.commit()
    post(
        client, f"/suchen/{s.id}", url=s.url, name="Neuer Name", interval_min="10", silence_days="0"
    )
    session.expire_all()
    s = session.get(Search, s.id)
    assert (s.name, s.interval_s, s.silence_days, s.last_ok_at) == ("Neuer Name", 600, 0, NOW)
    assert session.query(Seen).count() == 1


def test_url_change_resets_search(client, session):
    s = make_search(session, last_ok_at=NOW)
    session.add(
        Seen(
            search_id=s.id,
            platform="kleinanzeigen",
            external_id="1",
            status="seeded",
            listing_json="{}",
            first_seen_at=NOW,
        )
    )
    session.commit()
    post(client, f"/suchen/{s.id}", url=KA_URL, name="Jacken", interval_min="5", silence_days="7")
    session.expire_all()
    s = session.get(Search, s.id)
    assert (s.last_ok_at, s.url) == (
        None,
        "https://www.kleinanzeigen.de/s-sortierung:neueste/jacke/k0",
    )
    assert session.query(Seen).count() == 0


def test_pause_resume_delete_check_now(client, make_app, session):
    s = make_search(session, next_check_at=NOW + timedelta(hours=1))
    session.commit()
    post(client, f"/suchen/{s.id}/pausieren")
    session.expire_all()
    assert (session.get(Search, s.id).active, session.get(Search, s.id).state) == (False, "paused")
    post(client, f"/suchen/{s.id}/fortsetzen")
    session.expire_all()
    s2 = session.get(Search, s.id)
    assert (s2.active, s2.state, s2.next_check_at) == (True, "pending", NOW)
    post(client, f"/suchen/{s.id}/pruefen")
    assert client.application.scheduler.checked == [s.id]
    post(client, f"/suchen/{s.id}/loeschen")
    session.expire_all()
    assert session.query(Search).count() == 0


def test_hits_page_hides_seeded_and_shows_reason(client, session):
    import json

    from tests.engine.helpers import listing

    s = make_search(session)
    for i, status, reason in [(1, "seeded", None), (2, "matched", None), (3, "rejected", "zu alt")]:
        session.add(
            Seen(
                search_id=s.id,
                platform="kleinanzeigen",
                external_id=str(i),
                status=status,
                reason=reason,
                listing_json=json.dumps(listing(i).to_dict()),
                first_seen_at=NOW,
            )
        )
    session.commit()
    page = client.get("/treffer").get_data(as_text=True)
    assert "Jacke 1" not in page
    assert "Jacke 2" in page and "gemeldet" in page
    assert "Jacke 3" in page and "verworfen: zu alt" in page


def test_post_without_csrf_rejected(client, session):
    resp = client.post("/suchen/neu", data={"url": KA_URL})
    assert resp.status_code == 400
