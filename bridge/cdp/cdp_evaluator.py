"""CDP JavaScript evaluator — execute JS in the IDE's browser context."""

import logging

from bridge.cdp.cdp_connection import CdpConnection

logger = logging.getLogger(__name__)


class CdpEvaluator:
    """Evaluates JavaScript expressions in the IDE's browser context via CDP.

    Wraps Runtime.evaluate calls with error handling and
    convenience methods for common DOM operations.
    """

    def __init__(self, connection: CdpConnection) -> None:
        """Initialize the evaluator.

        Args:
            connection: An active CdpConnection to the target.
        """
        self.connection = connection

    async def evaluate(self, expression: str, return_by_value: bool = True) -> dict | None:
        """Execute a JavaScript expression and return the result.

        Args:
            expression: JavaScript code to execute.
            return_by_value: If True, return the result as a Python dict/value.

        Returns:
            The evaluated result, or None if evaluation failed.

        Raises:
            ConnectionError: If not connected to CDP.
        """
        params = {
            "expression": expression,
            "returnByValue": return_by_value,
        }
        try:
            result = await self.connection.send("Runtime.evaluate", params)
            cdp_result = result.get("result", {})

            if cdp_result.get("subtype") == "error":
                description = cdp_result.get("description", "unknown error")
                logger.error("JS evaluation error: %s", description)
                return None

            value = cdp_result.get("value")
            logger.debug("JS evaluate result type=%s", cdp_result.get("type"))
            return value
        except (ConnectionError, TimeoutError, RuntimeError) as e:
            logger.error("CDP evaluate failed: %s", e)
            raise

    async def query_selector(self, selector: str, root: str = "document") -> bool:
        """Check if a DOM element matching the selector exists.

        Args:
            selector: CSS selector string.
            root: JavaScript expression for the root element to search from.

        Returns:
            True if the element exists, False otherwise.
        """
        escaped = selector.replace("\\", "\\\\").replace('"', '\\"')
        expression = f'!!{root}.querySelector("{escaped}")'
        result = await self.evaluate(expression)
        return bool(result)

    async def query_selector_all_count(self, selector: str, root: str = "document") -> int:
        """Count DOM elements matching the selector.

        Args:
            selector: CSS selector string.
            root: JavaScript expression for the root element to search from.

        Returns:
            Number of matching elements.
        """
        escaped = selector.replace("\\", "\\\\").replace('"', '\\"')
        expression = f'{root}.querySelectorAll("{escaped}").length'
        result = await self.evaluate(expression)
        return int(result) if result is not None else 0

    async def get_text_content(self, selector: str, root: str = "document") -> str | None:
        """Get the text content of a DOM element.

        Args:
            selector: CSS selector string.
            root: JavaScript expression for the root element to search from.

        Returns:
            Text content of the element, or None if not found.
        """
        escaped = selector.replace("\\", "\\\\").replace('"', '\\"')
        expression = f'(function() {{ var el = {root}.querySelector("{escaped}"); return el ? el.textContent : null; }})()'
        return await self.evaluate(expression)

    async def click_element(self, selector: str, root: str = "document") -> bool:
        """Click a DOM element.

        Args:
            selector: CSS selector string.
            root: JavaScript expression for the root element to search from.

        Returns:
            True if the element was found and clicked, False otherwise.
        """
        escaped = selector.replace("\\", "\\\\").replace('"', '\\"')
        expression = f'(function() {{ var el = {root}.querySelector("{escaped}"); if (el) {{ el.click(); return true; }} return false; }})()'
        result = await self.evaluate(expression)
        if result:
            logger.info("Clicked element: %s", selector)
        else:
            logger.warning("Element not found for click: %s", selector)
        return bool(result)

    async def set_contenteditable_text(self, selector: str, text: str, root: str = "document") -> bool:
        """Set text in a contenteditable element (like Cascade's chat input).

        Uses DOM manipulation + input event dispatching to simulate typing.

        Args:
            selector: CSS selector for the contenteditable element.
            text: Text to insert.
            root: JavaScript expression for the root element.

        Returns:
            True if the text was set, False if the element wasn't found.
        """
        escaped_selector = selector.replace("\\", "\\\\").replace('"', '\\"')
        escaped_text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        expression = f"""(function() {{
            var el = {root}.querySelector("{escaped_selector}");
            if (!el) return false;
            el.focus();
            el.textContent = "{escaped_text}";
            el.dispatchEvent(new Event("input", {{bubbles: true}}));
            return true;
        }})()"""
        result = await self.evaluate(expression)
        if result:
            logger.info("Set contenteditable text (%d chars)", len(text))
        else:
            logger.warning("Contenteditable element not found: %s", selector)
        return bool(result)
