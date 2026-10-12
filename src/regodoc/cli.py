"""Comando ``regodoc``: punto d'ingresso del motore per Rego e per chi lo usa da solo.

Il comando non lascia mai arrivare all'utente un'eccezione grezza: ogni esito è un codice
d'uscita della tabella ``ExitCode`` e un messaggio in italiano su stderr, oppure un rapporto
JSON su stdout con l'opzione ``--json``.
"""

import argparse
import enum
import json
import re
import sys
from collections.abc import Sequence
from typing import IO, NoReturn

from regodoc import __version__, declaration


class ExitCode(enum.IntEnum):
    """Codici d'uscita del comando. Fanno parte del contratto con Rego."""

    OK = 0  # esito positivo, anche con avvisi (senza --strict)
    REFUSED = 1  # pacchetto rifiutato per errori di validazione, o avvisi con --strict
    USAGE = 2  # errore d'uso: argomenti, file mancante, opzione sconosciuta
    ENVIRONMENT = 3  # errore d'ambiente: TeX assente, cartella non scrivibile, tempo superato
    INTERNAL = 4  # eccezione non prevista: non deve mai accadere, è un difetto del motore
    INTERRUPTED = 130  # interrotto dall'utente


# Messaggi di argparse tradotti. argparse non ha una traduzione italiana e cambiare la sua
# funzione gettext toccherebbe tutti i parser del processo, anche quelli di chi ci importa:
# traduciamo quindi solo i messaggi dei nostri parser, nel metodo error().
_ARGPARSE_MESSAGES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"the following arguments are required: (?P<a>.+)"), "mancano gli argomenti {a}"),
    (re.compile(r"unrecognized arguments: (?P<a>.+)"), "argomenti non riconosciuti: {a}"),
    (
        re.compile(r"argument (?P<a>\S+): invalid choice: (?P<v>.+?) \(choose from (?P<c>.+)\)"),
        "valore {v} non ammesso per {a}; valori ammessi: {c}",
    ),
    (re.compile(r"argument (?P<a>\S+): expected one argument"), "{a} richiede un valore"),
    (
        re.compile(r"argument (?P<a>\S+): ignored explicit argument (?P<v>.+)"),
        "{a} non accetta il valore {v}",
    ),
    (
        re.compile(r"ambiguous option: (?P<o>\S+) could match (?P<m>.+)"),
        "l'opzione {o} è ambigua: può essere {m}",
    ),
    (
        re.compile(r"argument (?P<a>\S+): not allowed with argument (?P<b>\S+)"),
        "{a} non si può usare insieme a {b}",
    ),
)


def translate_argparse_message(message: str) -> str:
    """Traduce in italiano un messaggio d'errore di argparse.

    Un messaggio che non conosciamo resta riconoscibile: lo riportiamo fra virgolette dopo
    una frase italiana, così l'utente capisce comunque che cosa non va.
    """
    for pattern, template in _ARGPARSE_MESSAGES:
        match = pattern.fullmatch(message)
        if match:
            return template.format(**match.groupdict())
    return f"riga di comando non valida («{message}»)"


class _ItalianHelpFormatter(argparse.HelpFormatter):
    """Formattatore dell'aiuto con il prefisso «uso:» al posto di «usage:»."""

    def add_usage(self, usage, actions, groups, prefix=None):  # type: ignore[no-untyped-def]
        """Aggiunge la riga d'uso con il prefisso italiano."""
        return super().add_usage(
            usage, actions, groups, prefix="uso: " if prefix is None else prefix
        )


class ItalianArgumentParser(argparse.ArgumentParser):
    """ArgumentParser con aiuto e messaggi d'errore in italiano."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        """Crea il parser con i titoli italiani e l'opzione d'aiuto tradotta."""
        kwargs.setdefault("formatter_class", _ItalianHelpFormatter)
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self._positionals.title = "argomenti"
        self._optionals.title = "opzioni"
        self.add_argument(
            "-h", "--help", action="help", default=argparse.SUPPRESS, help="mostra questo aiuto"
        )

    def error(self, message: str) -> NoReturn:
        """Stampa l'uso e l'errore in italiano, poi esce con il codice d'uso."""
        self.print_usage(sys.stderr)
        _write(sys.stderr, f"{self.prog}: errore: {translate_argparse_message(message)}\n")
        raise SystemExit(ExitCode.USAGE)


def _write(stream: IO[str], text: str) -> None:
    """Scrive testo in UTF-8 qualunque sia la localizzazione del terminale."""
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(text)
    else:
        stream.flush()
        buffer.write(text.encode("utf-8"))
        buffer.flush()


def _write_json(payload: object) -> None:
    """Scrive un oggetto JSON su stdout, leggibile e con chiavi in ordine stabile."""
    _write(sys.stdout, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def build_parser() -> ItalianArgumentParser:
    """Costruisce il parser del comando con tutti i sottocomandi."""
    parser = ItalianArgumentParser(
        prog="regodoc",
        description="Motore del formato di pacchetto .regodoc.",
    )
    parser.add_argument(
        "--version", action="version", version=f"regodoc {__version__}", help="mostra la versione"
    )
    commands = parser.add_subparsers(dest="command", metavar="COMANDO", title="comandi")
    commands.required = True

    info = commands.add_parser("info", help="dichiara versione, grammatiche, limiti e capacità")
    info.set_defaults(handler=_cmd_info)

    validate = commands.add_parser("validate", help="controlla un pacchetto .regodoc")
    _add_package(validate)
    _add_json(validate)
    validate.set_defaults(handler=_cmd_draft, lot="L4")

    canon = commands.add_parser("canon", help="riscrive un pacchetto in forma canonica")
    _add_package(canon)
    _add_output(canon)
    _add_json(canon)
    canon.set_defaults(handler=_cmd_draft, lot="L4")

    build = commands.add_parser("build", help="produce LaTeX o PDF da un pacchetto")
    _add_package(build)
    _add_output(build)
    build.add_argument(
        "--format", choices=("pdf", "latex"), default="pdf", help="formato d'uscita (pdf)"
    )
    build.add_argument("--header", metavar="FILE", help="intestazione in JSON fornita da Rego")
    build.add_argument("--theme", metavar="CARTELLA", help="cartella di un tema esterno")
    _add_json(build)
    build.set_defaults(handler=_cmd_draft, lot="L5")

    upgrade = commands.add_parser("upgrade", help="porta un pacchetto alla grammatica corrente")
    _add_package(upgrade)
    _add_output(upgrade)
    _add_json(upgrade)
    upgrade.set_defaults(handler=_cmd_draft, lot="L6")

    return parser


def _add_package(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("package", metavar="PACCHETTO", help="percorso del file .regodoc")


def _add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--output", metavar="PERCORSO", required=True, help="file d'uscita")


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="scrive il rapporto in JSON su stdout")
    parser.add_argument(
        "--strict", action="store_true", help="tratta gli avvisi come errori (codice 1)"
    )


def _cmd_info(_args: argparse.Namespace) -> ExitCode:
    _write_json(declaration.describe())
    return ExitCode.OK


def _cmd_draft(args: argparse.Namespace) -> ExitCode:
    message = (
        f"il comando «{args.command}» non è ancora implementato: arriva con il lotto {args.lot}"
    )
    if args.json:
        _write_json(
            {
                "contract": declaration.CONTRACT_VERSION,
                "engine": {"name": declaration.ENGINE_NAME, "version": __version__},
                "command": args.command,
                "ok": False,
                "errors": [{"code": "regodoc.not_implemented", "message": message}],
                "warnings": [],
            }
        )
    else:
        _write(sys.stderr, f"regodoc: {message}\n")
    # Un comando non ancora implementato è un limite di questa versione del motore, cioè
    # dell'ambiente, non del pacchetto né della riga di comando.
    return ExitCode.ENVIRONMENT


def main(argv: Sequence[str] | None = None) -> int:
    """Esegue il comando e restituisce il codice d'uscita."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        return int(args.handler(args))
    except SystemExit as exit_:
        # argparse esce con SystemExit per l'aiuto, la versione e gli errori d'uso.
        return exit_.code if isinstance(exit_.code, int) else int(ExitCode.USAGE)
    except KeyboardInterrupt:
        _write(sys.stderr, "regodoc: interrotto\n")
        return int(ExitCode.INTERRUPTED)
    except Exception as error:
        _write(
            sys.stderr,
            f"regodoc: errore interno del motore ({type(error).__name__}); "
            "è un difetto del motore, non del pacchetto\n",
        )
        return int(ExitCode.INTERNAL)
