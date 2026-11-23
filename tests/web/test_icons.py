import json


def test_pages_link_icons_and_manifest(client):
    page = client.get("/suchen").get_data(as_text=True)
    assert 'rel="icon" href="/static/icon.svg"' in page
    assert 'rel="apple-touch-icon" href="/static/apple-touch-icon.png"' in page
    assert 'rel="manifest" href="/static/manifest.webmanifest"' in page
    assert '<meta name="apple-mobile-web-app-title" content="Sniper">' in page


def test_icon_files_are_served(client):
    for name in (
        "icon.svg",
        "favicon-32.png",
        "apple-touch-icon.png",
        "icon-192.png",
        "icon-512.png",
    ):
        assert client.get(f"/static/{name}").status_code == 200, name


def test_manifest(client):
    manifest = json.loads(client.get("/static/manifest.webmanifest").get_data(as_text=True))
    assert (manifest["name"], manifest["short_name"], manifest["display"]) == (
        "Marktplatz-Sniper",
        "Sniper",
        "standalone",
    )
    assert {i["sizes"] for i in manifest["icons"]} == {"192x192", "512x512"}


def test_login_page_has_icon_too(make_app):
    page = make_app(password="geheim123").test_client().get("/login").get_data(as_text=True)
    assert 'rel="icon"' in page
