from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from tui.logging_config import logger


class ConfirmDeletionModal(ModalScreen[bool]):
    """Modal sencillo para confirmar el envío a la Papelera."""

    BINDINGS = [
        Binding("y", "confirm", "", show=False),
        Binding("s", "confirm", "", show=False),
        Binding("n", "cancel", "", show=False),
        Binding("escape", "cancel", "", show=False),
    ]

    def __init__(self, message: str, strings: dict):
        super().__init__()
        self.message = message
        self.strings = strings

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self.message, id="confirm_message"),
            Static(
                self.strings.get(
                    "confirm_shortcuts",
                    "Teclas: S o Y para Sí · N para No · Esc para cancelar",
                ),
                id="confirm_shortcuts",
            ),
            Horizontal(
                Button(self.strings["yes"], id="confirm_yes", variant="success"),
                Button(self.strings["no"], id="confirm_no", variant="primary"),
                id="confirm_buttons",
            ),
            id="confirm_container",
        )

    def on_mount(self) -> None:
        self.query_one("#confirm_yes", Button).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        logger.info("Modal button pressed: %s", event.button.id)
        self.dismiss(event.button.id == "confirm_yes")

    def action_confirm(self) -> None:
        logger.info("Modal confirm action triggered")
        self.dismiss(True)

    def action_cancel(self) -> None:
        logger.info("Modal cancel action triggered")
        self.dismiss(False)


class MixedDeletionModal(ModalScreen[str]):
    """Modal con tres opciones para casos mixtos: borrar todo, sólo lo que entra o cancelar."""

    BINDINGS = [
        Binding("y", "choose_all", "", show=False),
        Binding("s", "choose_all", "", show=False),
        Binding("f", "choose_fit", "", show=False),
        Binding("n", "cancel", "", show=False),
        Binding("escape", "cancel", "", show=False),
    ]

    def __init__(self, message: str, strings: dict):
        super().__init__()
        self.message = message
        self.strings = strings

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self.message, id="confirm_message"),
            Static(
                self.strings.get(
                    "mixed_shortcuts",
                    "Teclas: S/Y = Todo · F = Sólo los que entran · N = No · Esc = Cancelar",
                ),
                id="confirm_shortcuts",
            ),
            Horizontal(
                Button(self.strings.get("yes", "Sí"), id="confirm_all", variant="success"),
                Button(self.strings.get("only_fit", "Sólo los que entran"), id="confirm_fit", variant="warning"),
                Button(self.strings.get("no", "No"), id="confirm_no", variant="primary"),
                id="confirm_buttons",
            ),
            id="confirm_container",
        )

    def on_mount(self) -> None:
        self.query_one("#confirm_all", Button).focus()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        logger.info("Mixed modal button pressed: %s", event.button.id)
        if event.button.id == "confirm_all":
            self.dismiss("all")
        elif event.button.id == "confirm_fit":
            self.dismiss("fit")
        else:
            self.dismiss("cancel")

    def action_choose_all(self) -> None:
        logger.info("Mixed modal choose_all action")
        self.dismiss("all")

    def action_choose_fit(self) -> None:
        logger.info("Mixed modal choose_fit action")
        self.dismiss("fit")

    def action_cancel(self) -> None:
        logger.info("Mixed modal cancel action")
        self.dismiss("cancel")
