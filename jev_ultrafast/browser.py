"""Observed actions through Browser Harness; one CDP session, no per-step subprocess."""

import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import cdp

MARKER = """(() => {
  if (!document.documentElement) return null;
  if (!window.__jevVersion) {
    window.__jevVersion = {n: 1};
    const bump = () => window.__jevVersion.n++;
    new MutationObserver(bump).observe(document.documentElement,
      {subtree:true,childList:true,attributes:true,characterData:true});
    addEventListener('input', bump, true); addEventListener('change', bump, true);
  }
  return [performance.timeOrigin, location.href, window.__jevVersion.n, scrollX, scrollY,
    [...document.querySelectorAll('input,textarea,select')]
      .filter(e=>!['password','file','hidden'].includes(e.type))
      .map(e=>[e.value,e.checked,e.selectedIndex])];
})()"""


class StalePage(ValueError):
    """A decision no longer refers to the observed page."""


class Browser:
    def __init__(self, url):
        ensure_daemon()
        self.objects = {}
        self.document_id = None
        self.readers = ThreadPoolExecutor(max_workers=8)
        self.target = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
        self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
        # Keep rAF/menus rendering in an owned background tab, without activating the user's Chrome tab.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.evaluate("document.readyState") == "complete":
                break
            time.sleep(0.02)

    def call(self, method, **params):
        return cdp(method, session_id=self.session, **params)

    def evaluate(self, expression):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def observe(self, screenshot=True):
        for attempt in range(10):
            try:
                return browser_operation(
                    {"operation": "observe", "session": self.session, "screenshot": screenshot, "layout": self.layout}
                )
            except StalePage:
                if attempt == 9:
                    raise
                time.sleep(0.02)
        raise StalePage("Page did not settle")

    def layout(self, nodes, document_id):
        """Read current geometry for AX candidates without copying scripts or the entire DOM."""
        if document_id != self.document_id or len(self.objects) > 1000:
            self.call("Runtime.releaseObjectGroup", objectGroup="jev-layout")
            self.objects.clear()
            self.document_id = document_id

        def resolve(backend):
            try:
                obj = self.call("DOM.resolveNode", backendNodeId=backend, objectGroup="jev-layout")
                return backend, obj["object"]["objectId"]
            except RuntimeError:
                return backend, None  # Detached between AX capture and resolution.

        missing = {n["backendDOMNodeId"] for n in nodes} - self.objects.keys()
        self.objects.update((backend, obj) for backend, obj in self.readers.map(resolve, missing) if obj)
        backends = [n["backendDOMNodeId"] for n in nodes if n["backendDOMNodeId"] in self.objects]
        references = [{"objectId": self.objects[backend]} for backend in backends]
        if not references:
            return {}
        response = self.call(
            "Runtime.callFunctionOn",
            objectId=references[0]["objectId"],
            arguments=references,
            returnByValue=True,
            functionDeclaration="""function(...elements) { return elements.map(e => {
              if (!e.isConnected || !e.getBoundingClientRect) return null;
              const r=e.getBoundingClientRect();
              return {x:r.x, y:r.y, w:r.width, h:r.height, tag:e.tagName,
                attrs:{type:e.getAttribute('type'), readonly:e.hasAttribute('readonly'),
                  placeholder:e.getAttribute('placeholder')},
                options:e.tagName==='SELECT' ? [...e.options].filter(o=>!o.disabled)
                  .map(o=>({value:o.value,label:o.label,selected:o.selected})) : []};
            }); }""",
        )
        if response.get("exceptionDetails"):
            self.objects.clear()
            raise StalePage("Document changed while reading target geometry")
        return {backend: element for backend, element in zip(backends, response["result"]["value"]) if element}

    def fresh(self, page):
        return self.evaluate(MARKER) == page["marker"]

    def act(self, action, page, text=None):
        if not self.fresh(page):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            time.sleep(0.1)
        return browser_operation({"operation": "act", "session": self.session, "action": action, "text": text})

    def close(self):
        self.readers.shutdown(wait=True, cancel_futures=True)
        if self.target:
            cdp("Target.closeTarget", targetId=self.target)
            self.target = None


def fingerprint(state):
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def browser_operation(request):
    operation = request["operation"]
    session = request["session"]

    def call(method, **params):
        return cdp(method, session_id=session, **params)

    def evaluate(expression):
        result = call("Runtime.evaluate", expression=expression, returnByValue=True)
        if result.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return result.get("result", {}).get("value")

    if operation == "act":
        action = request["action"]
        kind = action["kind"]
        if kind == "scroll":
            call("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=650, deltaX=0, deltaY=action["delta"])
        elif kind != "wait":
            node = action["node"]
            # Resolve the observed backend node again. A replaced node fails instead of hitting a new index.
            obj = call("DOM.resolveNode", backendNodeId=node)["object"]["objectId"]
            if kind == "select":
                result = call(
                    "Runtime.callFunctionOn",
                    objectId=obj,
                    returnByValue=True,
                    functionDeclaration="""function(value) {
                      if (!this.isConnected || this.disabled || this.tagName !== 'SELECT') return false;
                      const option = [...this.options].find(o => o.value === value && !o.disabled);
                      if (!option) return false;
                      this.value = value;
                      this.dispatchEvent(new Event('input', {bubbles:true}));
                      this.dispatchEvent(new Event('change', {bubbles:true})); return true;
                    }""",
                    arguments=[{"value": action["value"]}],
                )
                if not result.get("result", {}).get("value"):
                    raise RuntimeError("Dropdown changed; observe again")
            else:
                box = call("DOM.getBoxModel", backendNodeId=node)["model"]["content"]
                x, y = sum(box[0::2]) / 4, sum(box[1::2]) / 4
                hit = call("DOM.getNodeForLocation", x=round(x), y=round(y))
                hit_obj = call("DOM.resolveNode", backendNodeId=hit["backendNodeId"])["object"]["objectId"]
                valid = call(
                    "Runtime.callFunctionOn",
                    objectId=obj,
                    returnByValue=True,
                    functionDeclaration=(
                        "function(hit){return this.isConnected && !this.disabled && this.contains(hit)}"
                    ),
                    arguments=[{"objectId": hit_obj}],
                )
                if not valid.get("result", {}).get("value"):
                    raise RuntimeError("Target is covered or changed; observe again")
                for event in ("mousePressed", "mouseReleased"):
                    call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)
                if kind == "fill":
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyDown",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                    )
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyUp",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                    )
                    call("Input.insertText", text=request["text"])
        return {"executed": action["id"]}

    marker = evaluate(MARKER)
    if marker is None:
        raise StalePage("Document is navigating")
    info = evaluate("""(() => {
      const words=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
      const range=document.createRange(); let node, length=0;
      while ((node=walker.nextNode()) && length<6000) {
        const value=node.textContent.trim(), parent=node.parentElement;
        if (!value || !parent || parent.closest('script,style,noscript,template') ||
            !parent.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) continue;
        range.selectNodeContents(node); const r=range.getBoundingClientRect();
        if (r.width>0 && r.height>0 && r.bottom>0 && r.top<innerHeight && r.right>0 && r.left<innerWidth) {
          words.push(value); length+=value.length;
        }
      }
      return {url:location.href,title:document.title,w:innerWidth,h:innerHeight,text:words.join('\\n'),
        scroll:{y:scrollY,height:document.documentElement.scrollHeight}};
    })()""")
    nodes = call("Accessibility.getFullAXTree")["nodes"]
    roles = {
        "button",
        "link",
        "checkbox",
        "radio",
        "switch",
        "tab",
        "menuitem",
        "menuitemradio",
        "option",
        "gridcell",
        "combobox",
        "textbox",
        "searchbox",
        "spinbutton",
    }
    candidates = [
        n
        for n in nodes
        if not n.get("ignored") and n.get("role", {}).get("value") in roles and n.get("backendDOMNodeId")
    ]
    rendered = request["layout"](candidates, marker[0])
    actions, texts, seen = [], [], set()
    for node in nodes:
        if node.get("ignored"):
            continue
        role = node.get("role", {}).get("value", "")
        name = node.get("name", {}).get("value", "")
        if role in {"alert", "status"} and name and name not in seen:
            texts.append(name)
            seen.add(name)
        props = {p["name"]: p.get("value", {}).get("value") for p in node.get("properties", [])}
        if role not in roles or props.get("disabled") or not node.get("backendDOMNodeId"):
            continue
        backend = node["backendDOMNodeId"]
        if backend not in rendered:
            continue
        try:
            element = rendered[backend]
            x, y, w, h = (element[k] for k in ("x", "y", "w", "h"))
            tag, attrs = element["tag"], element["attrs"]
            if w <= 0 or h <= 0 or not (0 <= x + w / 2 < info["w"] and 0 <= y + h / 2 < info["h"]):
                continue
            if attrs.get("type") in {"password", "file", "hidden"}:
                continue
            base = {
                "node": backend,
                "role": role,
                "label": name or attrs.get("placeholder") or role,
                "rect": {"x": x, "y": y, "w": w, "h": h},
            }
            value = node.get("value", {}).get("value", "")
            if "checked" in props:
                base["checked"] = props["checked"]
            if "selected" in props:
                base["selected"] = props["selected"]
            if role == "combobox" and tag == "SELECT":
                options = element["options"]
                for option in options:
                    if not option["selected"]:
                        actions.append(
                            {
                                **base,
                                "kind": "select",
                                "value": option["value"],
                                "current_value": value,
                                "label": f"{base['label']} → {option['label']}",
                            }
                        )
            else:
                editable = (
                    not attrs["readonly"]
                    and not props.get("readonly")
                    and (
                        role in {"textbox", "searchbox", "spinbutton"}
                        or (role == "combobox" and tag in {"INPUT", "TEXTAREA"})
                    )
                )
                kind = "fill" if editable else "click"
                actions.append({**base, "kind": kind, "value": value})
                if kind == "fill":
                    actions.append({**base, "kind": "click", "value": value, "label": f"Open {base['label']}"})
        except RuntimeError:
            continue  # Non-rendered or detached AX nodes are not actionable.
    total = len(actions)
    actions = actions[:250]
    for i, action in enumerate(actions, 1):
        action["id"] = f"e{i}"
    if info["scroll"]["y"] + info["h"] < info["scroll"]["height"] - 2:
        actions.append({"id": "scroll_down", "kind": "scroll", "label": "Scroll down", "delta": 560})
    if info["scroll"]["y"] > 0:
        actions.append({"id": "scroll_up", "kind": "scroll", "label": "Scroll up", "delta": -560})
    actions.extend([{"id": "wait", "kind": "wait", "label": "Wait for the page to update"}])
    info.update(
        actions=actions,
        text=(info.get("text", "") + "\n" + "\n".join(texts))[:6000],
        omitted_actions=max(0, total - 250),
    )
    info["marker"] = marker
    info["fingerprint"] = fingerprint(info)
    if evaluate(MARKER) != marker:
        raise StalePage("Page changed during observation")
    if request.get("screenshot", True):
        info["screenshot"] = call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
    return info
