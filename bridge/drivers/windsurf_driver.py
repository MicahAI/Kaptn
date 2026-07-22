"""Windsurf IDE driver — DOM selectors and interactions for Windsurf's Cascade panel."""

import logging

from bridge.cdp.cdp_evaluator import CdpEvaluator
from bridge.drivers.ide_driver import IDEDriver
from bridge.models import ApprovalCategory, ApprovalRequest, CascadeMessage

logger = logging.getLogger(__name__)


class WindsurfDriver(IDEDriver):
    """Driver for Windsurf IDE's Cascade AI assistant.

    Implements all DOM interactions for reading messages,
    detecting approvals, and injecting input into Cascade.

    Selectors mapped via live CDP inspection (2026-03-07).
    """

    name = "windsurf"
    process_name = "Windsurf"

    SELECTORS = {
        "panel_root": '#windsurf\\.cascadePanel',
        "chat_container": "#chat",
        "active_tab": '[id^="cascade-tab-"]',
        "scroll_area": ".cascade-scrollbar",
        "message_container_js": (
            'document.getElementById("windsurf.cascadePanel")'
            '.querySelector(".cascade-scrollbar")'
            '.querySelector(".pb-20 > .flex.flex-col.px-4")'
        ),
        "chat_input": "[contenteditable=true]",
        "input_wrapper": ".panel-border.panel-bg.shadow-menu",
        "submit_button": ".panel-border.panel-bg.shadow-menu button[type=submit]",
        "prose_blocks": '[class*="prose"][class*="prose-sm"]',
        "user_message_marker": ".flex.w-full.flex-row.transition-opacity",
        "feedback_marker": ".mark-js-ignore",
    }

    def __init__(self, evaluator: CdpEvaluator) -> None:
        """Initialize the Windsurf driver."""
        super().__init__(evaluator)

    def get_selectors(self) -> dict[str, str]:
        """Return all Windsurf DOM selectors."""
        return dict(self.SELECTORS)

    def get_launch_commands(self) -> dict[str, str]:
        """Return per-OS launch commands for Windsurf with CDP enabled."""
        return {
            "macos": "open -a Windsurf --args --remote-debugging-port=9222",
            "windows": "windsurf.exe --remote-debugging-port=9222",
            "linux": "windsurf --remote-debugging-port=9222",
        }

    async def scroll_to_bottom(self) -> bool:
        """Scroll the Cascade chat panel to the bottom.

        Windsurf uses scroll virtualization — only messages near the
        viewport are in the DOM. Scrolling to bottom ensures the latest
        messages are rendered and available for extraction.

        Returns:
            True if scroll was performed, False if panel not found.
        """
        expression = """(function() {
            var p = document.getElementById("windsurf.cascadePanel");
            if (!p) return false;
            var sc = p.querySelector(".cascade-scrollbar");
            if (!sc) return false;
            sc.scrollTop = sc.scrollHeight;
            return true;
        })()"""
        result = await self.evaluator.evaluate(expression)
        if result:
            logger.info("⬇️ scroll_to_bottom() fired")
        return bool(result)

    async def extract_messages(self, scroll: bool = False) -> list[CascadeMessage]:
        """Extract all visible messages from the Cascade chat panel.

        Args:
            scroll: If True, scroll to bottom first so virtualized content
                    renders the latest messages. Only use on initial scan.

        Returns:
            List of CascadeMessage objects in display order.
        """
        scroll_line = "sc.scrollTop = sc.scrollHeight;" if scroll else ""
        if scroll:
            logger.info("⬇️ extract_messages(scroll=True) — scrolling to bottom")
        expression = """(function() {
            var p = document.getElementById("windsurf.cascadePanel");
            if (!p) return {error: "no panel"};
            var sc = p.querySelector(".cascade-scrollbar");
            if (!sc) return {error: "no scroll area"};

            """ + scroll_line + """

            var container = sc.querySelector(".pb-20 > .flex.flex-col.px-4");
            if (!container) return {error: "no message container"};

            var messages = [];
            var children = Array.from(container.children);
            for (var i = 0; i < children.length; i++) {
                var child = children[i];
                var cls = child.className.toString();
                var hasProse = !!child.querySelector('[class*="prose"][class*="prose-sm"]');
                var hasUserMarker = !!child.querySelector(".flex.w-full.flex-row.transition-opacity");
                var isFeedback = cls.indexOf("mark-js-ignore") !== -1;
                var text = child.textContent.substring(0, 500);

                var role = "unknown";
                if (isFeedback) role = "feedback";
                else if (hasUserMarker) role = "user";
                else if (hasProse) role = "assistant";
                else if (child.tagName === "BUTTON" && text.indexOf("Show More") !== -1) role = "show_more";
                else role = "tool_call";

                var hasCode = hasProse && !!child.querySelector("pre, code");

                messages.push({
                    index: i,
                    role: role,
                    text: text,
                    hasProse: hasProse,
                    hasCode: hasCode
                });
            }
            return {messages: messages, total: children.length};
        })()"""

        result = await self.evaluator.evaluate(expression)
        if result is None or "error" in (result or {}):
            error = (result or {}).get("error", "evaluation failed")
            logger.warning("Failed to extract messages: %s", error)
            return []

        messages = []
        for msg_data in result.get("messages", []):
            messages.append(CascadeMessage(
                index=msg_data["index"],
                role=msg_data["role"],
                text=msg_data["text"],
                has_prose=msg_data.get("hasProse", False),
                has_code=msg_data.get("hasCode", False),
            ))

        logger.debug("Extracted %d messages from Cascade panel", len(messages))
        return messages

    async def detect_approval(self) -> ApprovalRequest | None:
        """Check if an approval dialog is currently visible in Cascade.

        Windsurf shows approvals as a banner button with text containing
        'Awaiting Approval' plus nearby icon-only action buttons. Also
        checks for inline text buttons ('Run', 'Allow', etc.) as fallback.

        Returns:
            An ApprovalRequest if approval is pending, None otherwise.
        """
        expression = """(function() {
            var p = document.getElementById("windsurf.cascadePanel");
            if (!p) return null;

            // Extract conversation tab UUID (e.g. "cascade-tab-3354a1cd-...")
            var tabEl = p.querySelector("[id^='cascade-tab-']");
            var tabId = tabEl ? tabEl.id.replace("cascade-tab-", "") : "";

            var allButtons = Array.from(p.querySelectorAll("button"));

            // Strategy 1: Look for Run/Skip approval buttons
            // Windsurf shows "Run" (green, may have icon chars) and "Skip"
            var runBtn = allButtons.find(function(b) {
                var t = b.textContent.toLowerCase().trim();
                return t.indexOf("run") === 0 || t === "allow" || t === "accept";
            });
            var skipBtn = allButtons.find(function(b) {
                var t = b.textContent.toLowerCase().trim();
                return t === "skip" || t === "deny" || t === "cancel" || t === "reject";
            });
            if (runBtn || skipBtn) {
                var ref = runBtn || skipBtn;
                var container = ref.closest(".flex.flex-col") || ref.parentElement;
                var context = container ? container.textContent.substring(0, 300) : "";
                return {found: true, type: "run_skip", tabId: tabId, context: context,
                        text: ref.textContent.trim().substring(0, 50),
                        hasRun: !!runBtn, hasSkip: !!skipBtn};
            }

            // Strategy 2: Look for "Awaiting Approval" banner
            var banner = allButtons.find(function(b) {
                var t = b.textContent.toLowerCase();
                return t.indexOf("awaiting") !== -1 && t.indexOf("approv") !== -1;
            });
            if (banner) {
                var container = banner.closest(".flex.flex-col") || banner.parentElement;
                var context = container ? container.textContent.substring(0, 300) : "";
                return {found: true, type: "banner", tabId: tabId, context: context,
                        text: banner.textContent.trim().substring(0, 50)};
            }

            // Strategy 3: Any button with "approv" text
            var approvalBtn = allButtons.find(function(b) {
                return b.textContent.toLowerCase().indexOf("approv") !== -1;
            });
            if (approvalBtn) {
                var context = approvalBtn.parentElement
                    ? approvalBtn.parentElement.textContent.substring(0, 200) : "";
                return {found: true, type: "generic", tabId: tabId, context: context,
                        text: approvalBtn.textContent.trim().substring(0, 50)};
            }

            return null;
        })()"""

        result = await self.evaluator.evaluate(expression)
        if not result or not result.get("found"):
            return None

        context_text = result.get("context", "")
        approval_type = result.get("type", "unknown")
        logger.debug("Approval detected (type=%s): %s", approval_type, context_text[:100])

        category = self._classify_approval(context_text)

        tab_id = result.get("tabId", "")

        return ApprovalRequest(
            category=category,
            action=result.get("text", "unknown"),
            details={"type": approval_type, "tab_id": tab_id, "context": context_text},
        )

    def _classify_approval(self, context: str) -> ApprovalCategory:
        """Classify an approval request into a category based on context text.

        Args:
            context: Text surrounding the approval buttons.

        Returns:
            The appropriate ApprovalCategory.
        """
        context_lower = context.lower()

        if any(kw in context_lower for kw in ["edit file", "create file", "write file", "modify"]):
            return ApprovalCategory.FILE_WRITE
        if any(kw in context_lower for kw in ["delete file", "remove file"]):
            return ApprovalCategory.FILE_DELETE
        if any(kw in context_lower for kw in ["read file", "view file"]):
            return ApprovalCategory.FILE_READ
        if any(kw in context_lower for kw in [
            "command", "run command", "execute", "terminal", "bash", "shell",
            "npm ", "pip ", "yarn ", "pnpm ", "cargo ", "make ", "docker ",
        ]):
            return ApprovalCategory.COMMAND_UNSAFE
        if any(kw in context_lower for kw in [
            "echo ", "ls ", "cat ", "pwd", "mkdir ", "cd ",
        ]):
            return ApprovalCategory.COMMAND_SAFE
        if any(kw in context_lower for kw in ["search", "grep", "find"]):
            return ApprovalCategory.SEARCH
        if any(kw in context_lower for kw in ["tool", "mcp"]):
            return ApprovalCategory.TOOL_CALL

        logger.debug("Could not classify approval context: %s", context[:100])
        return ApprovalCategory.UNKNOWN

    async def inject_message(self, text: str) -> bool:
        """Type a message into Cascade's chat input and submit.

        Args:
            text: Message text to send.

        Returns:
            True if message was sent successfully.
        """
        panel_root = 'document.getElementById("windsurf.cascadePanel")'
        input_selector = "[contenteditable=true]"

        set_ok = await self.evaluator.set_contenteditable_text(
            input_selector, text, root=panel_root
        )
        if not set_ok:
            logger.error("Failed to set chat input text")
            return False

        click_ok = await self.evaluator.click_element(
            "button[type=submit]",
            root=f'{panel_root}.querySelector(".panel-border.panel-bg.shadow-menu")',
        )
        if not click_ok:
            logger.error("Failed to click submit button")
            return False

        logger.info("Message injected into Cascade (%d chars)", len(text))
        return True

    async def click_approval_banner(self) -> bool:
        """Click the 'Awaiting Approval' banner to scroll/navigate to the approval area.

        This is a navigation action, NOT an approval. After clicking,
        the Run/Skip buttons should become visible on the next poll.

        Returns:
            True if the banner was found and clicked.
        """
        expression = """(function() {
            var p = document.getElementById("windsurf.cascadePanel");
            if (!p) return false;
            var btns = Array.from(p.querySelectorAll("button"));
            var banner = btns.find(function(b) {
                var t = b.textContent.toLowerCase();
                return t.indexOf("awaiting") !== -1 && t.indexOf("approv") !== -1;
            });
            if (banner) { banner.click(); return true; }
            return false;
        })()""";
        result = await self.evaluator.evaluate(expression)
        if result:
            logger.info("Clicked approval banner to navigate")
        return bool(result)

    async def click_approve(self) -> bool:
        """Click the Run/Allow button on the current approval dialog.

        Only clicks actual approval action buttons (Run, Allow, Accept).
        Never clicks the 'Awaiting Approval' banner.

        Returns:
            True if the button was found and clicked.
        """
        expression = """(function() {
            var p = document.getElementById("windsurf.cascadePanel");
            if (!p) return {clicked: false, reason: "no panel"};
            var btns = Array.from(p.querySelectorAll("button"));

            // Strategy 1: Click "Run" button (Windsurf's approve action)
            var runBtn = btns.find(function(b) {
                var t = b.textContent.toLowerCase().trim();
                return t.indexOf("run") === 0;
            });
            if (runBtn) {
                runBtn.click();
                return {clicked: true, strategy: "run_button", text: runBtn.textContent.trim()};
            }

            // Strategy 2: "Allow" / "Accept" (exclude 'awaiting' banner)
            var allowBtn = btns.find(function(b) {
                var t = b.textContent.toLowerCase().trim();
                return (t === "allow" || t === "accept")
                    && t.indexOf("awaiting") === -1;
            });
            if (allowBtn) {
                allowBtn.click();
                return {clicked: true, strategy: "allow_button", text: allowBtn.textContent.trim()};
            }

            return {clicked: false, reason: "no Run or Allow button found"};
        })()"""
        result = await self.evaluator.evaluate(expression)
        if result and result.get("clicked"):
            logger.info("Clicked APPROVE (%s)", result.get("strategy"))
            return True
        logger.warning("No approve button found: %s", result.get("reason") if result else "eval failed")
        return False

    async def click_deny(self) -> bool:
        """Click the deny/skip button on the current approval dialog.

        Returns:
            True if the button was found and clicked.
        """
        expression = """(function() {
            var p = document.getElementById("windsurf.cascadePanel");
            if (!p) return false;
            var btns = Array.from(p.querySelectorAll("button"));
            var deny = btns.find(function(b) {
                var t = b.textContent.toLowerCase().trim();
                return t === "skip" || t === "deny" || t === "cancel" || t === "reject";
            });
            if (deny) { deny.click(); return true; }
            return false;
        })()"""
        result = await self.evaluator.evaluate(expression)
        if result:
            logger.info("Clicked DENY button")
        else:
            logger.warning("No deny button found to click")
        return bool(result)

    async def install_message_observer(self) -> bool:
        """Inject a MutationObserver that captures messages as they appear in the DOM.

        This bypasses scroll virtualization by watching for new child nodes
        in real-time rather than scraping the current DOM state.

        The observer stores messages in window.__kaptnMessages which can
        be drained via drain_observed_messages().

        Returns:
            True if the observer was installed successfully.
        """
        expression = """(function() {
            // Disconnect previous observer if present (code may have changed)
            if (window.__kaptnObserver) {
                window.__kaptnObserver.disconnect();
                window.__kaptnObserver = null;
            }

            window.__kaptnMessages = [];
            window.__kaptnConversationId = "";

            // Detect "Thinking" or "Thought for Xs" prefix in text
            var thinkingRe = /^(Thinking|Thought\\s*for\\s*\\d+s?)/;

            function splitThinking(text) {
                var m = text.match(thinkingRe);
                if (!m) return null;
                var prefix = m[1];
                var rest = text.substring(prefix.length).trim();
                return {thinking: prefix, rest: rest};
            }

            function classifyNode(node) {
                if (!node || node.nodeType !== 1) return null;
                var text = (node.textContent || "").substring(0, 2000);
                if (!text.trim()) return null;

                var tag = node.tagName;
                var cls = (node.className || "").toString();

                // Skip "Show More" buttons
                if (tag === "BUTTON" && text.indexOf("Show More") !== -1) return null;

                // Check for user message marker
                var hasUserMarker = !!node.querySelector(".flex.w-full.flex-row.transition-opacity");

                // Check for prose content (AI response)
                var hasProse = !!node.querySelector('[class*="prose"][class*="prose-sm"]');

                // Also check if the node itself has prose classes
                if (!hasProse) {
                    hasProse = cls.indexOf("prose") !== -1 && cls.indexOf("prose-sm") !== -1;
                }

                // Walk direct children to find individual messages within grouped containers
                var children = Array.from(node.children);
                var found = [];

                for (var i = 0; i < children.length; i++) {
                    var child = children[i];
                    var cCls = (child.className || "").toString();
                    var cText = (child.textContent || "").substring(0, 2000).trim();
                    if (!cText) continue;

                    var childHasUser = !!child.querySelector(".flex.w-full.flex-row.transition-opacity")
                        || cCls.indexOf("transition-opacity") !== -1;
                    var childHasProse = !!child.querySelector('[class*="prose"][class*="prose-sm"]')
                        || (cCls.indexOf("prose") !== -1 && cCls.indexOf("prose-sm") !== -1);

                    if (childHasUser) {
                        found.push({role: "user", text: cText});
                    } else if (childHasProse) {
                        // Check for thinking prefix in assistant text
                        var split = splitThinking(cText);
                        if (split) {
                            found.push({role: "thinking", text: split.thinking});
                            if (split.rest) found.push({role: "assistant", text: split.rest});
                        } else {
                            found.push({role: "assistant", text: cText});
                        }
                    }
                }

                // If we found individual messages in children, return them
                if (found.length > 0) return found;

                // Fallback: classify the node itself
                if (hasUserMarker) return [{role: "user", text: text}];
                if (hasProse) {
                    var split = splitThinking(text);
                    if (split) {
                        var results = [{role: "thinking", text: split.thinking}];
                        if (split.rest) results.push({role: "assistant", text: split.rest});
                        return results;
                    }
                    return [{role: "assistant", text: text}];
                }

                return null;
            }

            // Find or wait for message container
            function getContainer() {
                var p = document.getElementById("windsurf.cascadePanel");
                if (!p) return null;
                var sc = p.querySelector(".cascade-scrollbar");
                if (!sc) return null;
                return sc.querySelector(".pb-20 > .flex.flex-col.px-4");
            }

            // Detect conversation tab changes
            function getTabId() {
                var p = document.getElementById("windsurf.cascadePanel");
                if (!p) return "";
                var tab = p.querySelector("[id^='cascade-tab-']");
                return tab ? tab.id : "";
            }

            var container = getContainer();
            if (!container) return {installed: false, error: "no container"};

            window.__kaptnConversationId = getTabId();

            window.__kaptnObserver = new MutationObserver(function(mutations) {
                var currentTab = getTabId();
                if (currentTab !== window.__kaptnConversationId) {
                    window.__kaptnConversationId = currentTab;
                    window.__kaptnMessages.push({
                        type: "session_change",
                        timestamp: Date.now()
                    });
                }

                for (var m = 0; m < mutations.length; m++) {
                    var added = mutations[m].addedNodes;
                    for (var n = 0; n < added.length; n++) {
                        var result = classifyNode(added[n]);
                        if (result) {
                            for (var r = 0; r < result.length; r++) {
                                window.__kaptnMessages.push({
                                    type: "message",
                                    role: result[r].role,
                                    text: result[r].text,
                                    timestamp: Date.now()
                                });
                            }
                        }
                    }
                }
            });

            window.__kaptnObserver.observe(container, {childList: true, subtree: true});

            // Self-cleanup heartbeat timer
            // Bridge sends heartbeat via window.__kaptnHeartbeat = Date.now()
            // If heartbeat goes stale, cleanup after grace period
            window.__kaptnHeartbeat = Date.now();
            window.__kaptnCleanupPending = 0;

            if (window.__kaptnCleanupTimer) {
                clearInterval(window.__kaptnCleanupTimer);
            }

            window.__kaptnCleanupTimer = setInterval(function() {
                var now = Date.now();
                var hb = window.__kaptnHeartbeat || 0;
                var staleMs = 5 * 60 * 1000;  // 5 minutes
                var graceMs = 5 * 60 * 1000;  // 5 minutes

                if (now - hb < staleMs) {
                    // Heartbeat is fresh — reset any pending cleanup
                    window.__kaptnCleanupPending = 0;
                    return;
                }

                // Heartbeat is stale
                if (!window.__kaptnCleanupPending) {
                    // First stale detection — start grace period
                    window.__kaptnCleanupPending = now;
                    return;
                }

                if (now - window.__kaptnCleanupPending < graceMs) {
                    // Still in grace period — wait for bridge to reconnect
                    return;
                }

                // Grace period expired — self-destruct
                if (window.__kaptnObserver) {
                    window.__kaptnObserver.disconnect();
                }
                clearInterval(window.__kaptnCleanupTimer);

                // Remove all Kaptn globals
                delete window.__kaptnObserver;
                delete window.__kaptnMessages;
                delete window.__kaptnConversationId;
                delete window.__kaptnHeartbeat;
                delete window.__kaptnCleanupPending;
                delete window.__kaptnCleanupTimer;
            }, 60000);  // Check every 60 seconds

            return {installed: true, reused: false};
        })()"""

        result = await self.evaluator.evaluate(expression)
        if not result:
            logger.warning("Failed to install message observer")
            return False

        if result.get("installed"):
            logger.info("Message observer installed")
            return True

        logger.warning("Message observer install failed: %s", result.get("error"))
        return False

    async def drain_observed_messages(self) -> list[dict]:
        """Read and clear the message buffer populated by the MutationObserver.

        Returns:
            List of message dicts with keys: type, role, text, timestamp.
            Empty list if no new messages or observer not installed.
        """
        expression = """(function() {
            if (!window.__kaptnMessages) return [];
            var msgs = window.__kaptnMessages.slice();
            window.__kaptnMessages = [];
            return msgs;
        })()"""

        result = await self.evaluator.evaluate(expression)
        if not result or not isinstance(result, list):
            return []
        return result

    async def get_observer_status(self) -> dict:
        """Get the current status of the injected observer and heartbeat.

        Returns:
            Dict with keys:
            - installed (bool): Whether the observer is active.
            - heartbeat_age_ms (int): Milliseconds since last heartbeat, or -1.
            - cleanup_pending (bool): Whether cleanup grace period is active.
            - globals (list[str]): Which __kaptn* globals exist.
        """
        expression = """(function() {
            var globals = [];
            var keys = ["__kaptnObserver", "__kaptnMessages", "__kaptnConversationId",
                        "__kaptnHeartbeat", "__kaptnCleanupPending", "__kaptnCleanupTimer"];
            for (var i = 0; i < keys.length; i++) {
                if (window[keys[i]] !== undefined) globals.push(keys[i]);
            }
            var hb = window.__kaptnHeartbeat || 0;
            return {
                installed: !!window.__kaptnObserver,
                heartbeat_age_ms: hb ? Date.now() - hb : -1,
                cleanup_pending: !!window.__kaptnCleanupPending,
                globals: globals
            };
        })()"""
        result = await self.evaluator.evaluate(expression)
        if not result or not isinstance(result, dict):
            return {"installed": False, "heartbeat_age_ms": -1, "cleanup_pending": False, "globals": []}
        return result

    async def trigger_cleanup_check(self, stale_ms: int = 0, grace_ms: int = 0) -> dict:
        """Force-run the cleanup check logic with custom thresholds.

        This is for testing — it runs the same logic as the timer callback
        but with caller-specified thresholds so tests don't have to wait
        5+ minutes.

        Args:
            stale_ms: Stale threshold in ms (0 = immediately stale).
            grace_ms: Grace period in ms (0 = no grace).

        Returns:
            Dict with keys:
            - action (str): "fresh", "stale_pending", "grace_waiting", "cleaned".
            - heartbeat_age_ms (int): Age of heartbeat.
        """
        expression = f"""(function() {{
            var now = Date.now();
            var hb = window.__kaptnHeartbeat || 0;
            var staleMs = {stale_ms};
            var graceMs = {grace_ms};
            var age = hb ? now - hb : 999999999;

            if (age < staleMs) {{
                window.__kaptnCleanupPending = 0;
                return {{action: "fresh", heartbeat_age_ms: age}};
            }}

            if (!window.__kaptnCleanupPending) {{
                window.__kaptnCleanupPending = now;
                return {{action: "stale_pending", heartbeat_age_ms: age}};
            }}

            if (now - window.__kaptnCleanupPending < graceMs) {{
                return {{action: "grace_waiting", heartbeat_age_ms: age}};
            }}

            // Cleanup
            if (window.__kaptnObserver) {{
                window.__kaptnObserver.disconnect();
            }}
            if (window.__kaptnCleanupTimer) {{
                clearInterval(window.__kaptnCleanupTimer);
            }}
            delete window.__kaptnObserver;
            delete window.__kaptnMessages;
            delete window.__kaptnConversationId;
            delete window.__kaptnHeartbeat;
            delete window.__kaptnCleanupPending;
            delete window.__kaptnCleanupTimer;
            return {{action: "cleaned", heartbeat_age_ms: age}};
        }})()"""
        result = await self.evaluator.evaluate(expression)
        if not result or not isinstance(result, dict):
            return {"action": "error", "heartbeat_age_ms": -1}
        return result

    async def cleanup_injected_js(self) -> bool:
        """Remove all Kaptn-injected JS from the page.

        Disconnects the MutationObserver, clears the cleanup timer,
        and deletes all window.__kaptn* globals. Call this on connect
        to clean up stale JS from previous sessions.

        Returns:
            True if cleanup was performed.
        """
        expression = """(function() {
            var cleaned = false;
            if (window.__kaptnObserver) {
                window.__kaptnObserver.disconnect();
                cleaned = true;
            }
            if (window.__kaptnCleanupTimer) {
                clearInterval(window.__kaptnCleanupTimer);
                cleaned = true;
            }
            var keys = ["__kaptnObserver", "__kaptnMessages", "__kaptnConversationId",
                        "__kaptnHeartbeat", "__kaptnCleanupPending", "__kaptnCleanupTimer"];
            for (var i = 0; i < keys.length; i++) {
                if (window[keys[i]] !== undefined) {
                    delete window[keys[i]];
                    cleaned = true;
                }
            }
            return cleaned;
        })()"""
        result = await self.evaluator.evaluate(expression)
        if result:
            logger.info("Cleaned up stale Kaptn JS from page")
        return bool(result)

    async def send_heartbeat(self) -> bool:
        """Send a heartbeat ping to keep injected JS alive.

        Sets window.__kaptnHeartbeat to the current timestamp. The
        self-cleanup timer in the observer JS checks this value — if
        it goes stale (>5 min without update), the JS self-destructs.

        Returns:
            True if the heartbeat was set.
        """
        result = await self.evaluator.evaluate("window.__kaptnHeartbeat = Date.now()")
        return result is not None

    async def validate_selectors(self) -> dict[str, bool]:
        """Validate that critical Windsurf selectors resolve in the DOM.

        Returns:
            Dict mapping selector names to True (found) or False (missing).
        """
        critical_selectors = {
            "panel_root": '#windsurf\\.cascadePanel',
            "scroll_area": ".cascade-scrollbar",
            "chat_input": "[contenteditable=true]",
        }
        panel_root = 'document.getElementById("windsurf.cascadePanel")'
        results = {}

        for name, selector in critical_selectors.items():
            if name == "panel_root":
                found = await self.evaluator.evaluate('!!document.getElementById("windsurf.cascadePanel")')
            else:
                found = await self.evaluator.query_selector(selector, root=panel_root)
            results[name] = bool(found)
            if found:
                logger.debug("Selector '%s' validated OK", name)
            else:
                logger.warning("Selector '%s' NOT FOUND: %s", name, selector)

        return results

    async def get_status(self) -> str:
        """Get Cascade's current status.

        Returns:
            One of: 'idle', 'generating', 'waiting_for_approval', 'unknown'.
        """
        approval = await self.detect_approval()
        if approval:
            return "waiting_for_approval"

        expression = """(function() {
            var p = document.getElementById("windsurf.cascadePanel");
            if (!p) return "unknown";
            var btns = Array.from(p.querySelectorAll("button"));
            var stopBtn = btns.find(function(b) {
                var t = b.textContent.toLowerCase().trim();
                return t === "stop" || t.indexOf("stop generating") !== -1;
            });
            return stopBtn ? "generating" : "idle";
        })()"""
        result = await self.evaluator.evaluate(expression)
        return result if isinstance(result, str) else "unknown"
