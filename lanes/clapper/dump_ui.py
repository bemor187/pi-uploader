"""Print the phone's current screen elements, to calibrate clapper_flow.json.

Usage on the clapper Pi:
    cd /opt/uploader && sudo -u $USER ./venv/bin/python -m lanes.clapper.dump_ui
Walk through a Clapper post by hand, running this on each screen.
"""
import asyncio

from lanes.clapper.app import dump_nodes


async def main():
    for n in await dump_nodes():
        if n["text"] or n["desc"] or n["clickable"]:
            flags = ("C" if n["clickable"] else "-") + ("E" if n["enabled"] else "-")
            print(f"{flags} ({n['x']:4},{n['y']:4}) text={n['text']!r} desc={n['desc']!r} "
                  f"id={n['id']!r} class={n['class'].split('.')[-1]}")


if __name__ == "__main__":
    asyncio.run(main())
