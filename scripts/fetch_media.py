"""One-off: download public-domain media from Wikimedia Commons with license metadata.

Run by .github/workflows/fetch-media.yml. Refuses any file whose Commons license is not public domain.
"""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

UA = {"User-Agent": "supply-chain-resilience-media-fetch/1.0 (https://github.com/scucla/Supply-Chain-Resilience)"}
OUT = Path(__file__).resolve().parent.parent / "media_raw"
FILES = {
    "hero_mq9_flight.webm": "File:MQ-9 Reaper aerial video DOD 107212162-5e1342c0d88af.webm",
    "assembly_mq9.jpg": "File:Rise of the Reaper 140423-F-RS318-157.jpg",
    "assembly_line_1942.jpg": "File:B-25 final assembly line Inglewood 1942.jpg",
    "small_uas_flight.jpg": "File:Skydio drone flies during Dynamic Front 25 in Smârdan, Romania.jpg",
}


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def main():
    OUT.mkdir(exist_ok=True)
    credits = {}
    for name, title in FILES.items():
        api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo"
               "&iiprop=url|size|extmetadata&titles=" + urllib.parse.quote(title))
        page = next(iter(json.loads(get(api))["query"]["pages"].values()))
        info = page["imageinfo"][0]
        meta = {k: v.get("value", "") for k, v in info.get("extmetadata", {}).items()}
        lic = (meta.get("LicenseShortName", "") + " " + meta.get("License", "")).lower()
        if "public domain" not in lic and "pd" not in lic.split():
            print(f"SKIP {name}: license is {meta.get('LicenseShortName')!r}")
            continue
        (OUT / name).write_bytes(get(info["url"]))
        credits[name] = {"title": title, "page": info.get("descriptionurl"), "license": meta.get("LicenseShortName"),
                         "artist": meta.get("Artist", ""), "credit": meta.get("Credit", ""),
                         "description": meta.get("ImageDescription", "")[:400], "bytes": info.get("size")}
        print(f"OK   {name}: {meta.get('LicenseShortName')} | {info.get('size')} bytes")
    (OUT / "credits.json").write_text(json.dumps(credits, indent=2, ensure_ascii=False))
    if not credits:
        sys.exit("nothing downloaded")


if __name__ == "__main__":
    main()
