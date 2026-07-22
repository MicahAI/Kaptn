"""Quick CDP diagnostic — inspect Cascade message container DOM structure."""
import asyncio
import json
import urllib.request
import websockets


JS_INSPECT = """(function() {
    var p = document.getElementById("windsurf.cascadePanel");
    if (!p) return {error: "no panel"};
    var sc = p.querySelector(".cascade-scrollbar");
    if (!sc) return {error: "no scroll"};
    sc.scrollTop = sc.scrollHeight;
    var container = sc.querySelector(".pb-20 > .flex.flex-col.px-4");
    if (!container) return {error: "no container"};
    var children = Array.from(container.children);
    var results = [];
    for (var i = Math.max(0, children.length - 10); i < children.length; i++) {
        var c = children[i];
        var tag = c.tagName;
        var cls = c.className.toString().substring(0, 200);
        var text = c.textContent.substring(0, 80).replace(/\\n/g, " ");
        
        // Inspect children of each top-level element
        var subChildren = [];
        var subs = Array.from(c.children);
        for (var j = 0; j < Math.min(subs.length, 10); j++) {
            var s = subs[j];
            var sCls = s.className.toString().substring(0, 200);
            var sText = s.textContent.substring(0, 60).replace(/\\n/g, " ");
            var sHasProse = !!s.querySelector('[class*="prose"][class*="prose-sm"]');
            var sHasUser = !!s.querySelector(".flex.w-full.flex-row.transition-opacity");
            var sIsProse = s.className.toString().indexOf("prose") !== -1;
            subChildren.push({j: j, tag: s.tagName, cls: sCls, text: sText, hasProse: sHasProse, hasUser: sHasUser, isProse: sIsProse});
        }
        results.push({i: i, tag: tag, cls: cls, text: text, childCount: subs.length, children: subChildren});
    }
    return {total: children.length, items: results};
})()"""


async def main():
    targets = json.loads(urllib.request.urlopen("http://localhost:9222/json").read())
    for t in targets:
        title = t.get("title", "")
        print(f"  Window: {title[:60]}")
    for t in targets:
        title = t.get("title", "")
        if "Kaptn" in title and "Telemetry" not in title:
            ws_url = t["webSocketDebuggerUrl"]
            print(f"\nTarget: {title[:60]}")
            break
    else:
        print("No Kaptn window found")
        return

    async with websockets.connect(ws_url, max_size=2**20) as ws:
        msg = json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": JS_INSPECT, "returnByValue": True},
        })
        await ws.send(msg)
        resp = json.loads(await ws.recv())
        value = resp.get("result", {}).get("result", {}).get("value")
        if value:
            print(json.dumps(value, indent=2))
        else:
            print("Raw response:")
            print(json.dumps(resp, indent=2)[:2000])


asyncio.run(main())
