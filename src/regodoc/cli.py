"""Comando ``regodoc``: punto d'ingresso del motore per Rego e per chi lo usa da solo.

Il comando non lascia mai arrivare all'utente un'eccezione grezza: ogni esito è un codice
d'uscita della tabella ``ExitCode`` e un messaggio in italiano su stderr, oppure un rapporto
JSON su stdout con l'opzione ``--json``.
"""

import argparse
import contextlib
import enum
import io
import json
import os
import re
import stat
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import IO, NoReturn

from regodoc import __version__, declaration, limits
from regodoc.diagnostics import Severity, clip
from regodoc.validate import Validation, validate_package


class ExitCode(enum.IntEnum):
    """Codici d'uscita del comando. Fanno parte del contratto con Rego."""

    OK = 0  # esito positivo, anche con avvisi (senza --strict)
    REFUSED = 1  # pacchetto rifiutato per errori di validazione, o avvisi con --strict
    USAGE = 2  # errore d'uso: argomenti, file mancante, opzione sconosciuta
    ENVIRONMENT = 3  # errore d'ambiente: TeX assente, memoria esaurita, cartella non scrivibile
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
        re.compile(r"argument (?P<a>\S+): invalid int value: (?P<v>.+)"),
        "{a} vuole un numero intero, non {v}",
    ),
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
        kwargs["allow_abbrev"] = False  # un'opzione abbreviata non deve indovinare quella vera
        super().__init__(*args, **kwargs)
        self._positionals.title = "argomenti"
        self._optionals.title = "opzioni"
        self.add_argument(
            "-h", "--help", action="help", default=argparse.SUPPRESS, help="mostra questo aiuto"
        )

    def error(self, message: str) -> NoReturn:
        """Stampa l'uso e l'errore in italiano, poi esce con il codice d'uso."""
        translated = translate_argparse_message(message)
        self.print_usage(sys.stderr)
        _write(sys.stderr, f"{self.prog}: errore: {translated}\n")
        raise UsageExit(translated)


class UsageExit(SystemExit):
    """Uscita per un errore della riga di comando, con il messaggio già tradotto."""

    def __init__(self, message: str) -> None:
        super().__init__(ExitCode.USAGE)
        self.message = message


def _write(stream: IO[str], text: str) -> None:
    """Scrive testo in UTF-8 qualunque sia la localizzazione del terminale.

    Prima ferma il timer del comando: la scrittura non si interrompe mai a metà.
    """
    limits.disarm()
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        stream.write(text)
    else:
        stream.flush()
        buffer.write(text.encode("utf-8"))
        buffer.flush()


def _note(text: str) -> None:
    """Scrive un messaggio su stderr senza mai fallire: anche stderr può essere chiuso."""
    with contextlib.suppress(OSError, ValueError):
        _write(sys.stderr, text)


def _silence_stdout() -> None:
    """Dopo una pipe chiusa, punta stdout a /dev/null per evitare errori alla chiusura."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except (OSError, ValueError, io.UnsupportedOperation):
        pass


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
    parser.add_argument(
        "--contract",
        type=int,
        metavar="N",
        help="versione del contratto attesa da chi chiama (docs/contract.md)",
    )
    parser.add_argument(
        "--max-seconds",
        type=int,
        metavar="S",
        help="abbassa il tempo massimo del comando; un valore più alto è ignorato",
    )
    commands = parser.add_subparsers(dest="command", metavar="COMANDO", title="comandi")
    commands.required = True

    info = commands.add_parser("info", help="dichiara versione, grammatiche, limiti e capacità")
    info.add_argument(
        "--json", action="store_true", help="accettata per uniformità: info scrive sempre JSON"
    )
    info.set_defaults(handler=_cmd_info)

    validate = commands.add_parser("validate", help="controlla un pacchetto .regodoc")
    _add_package(validate)
    _add_json(validate)
    validate.set_defaults(handler=_cmd_validate)

    canon = commands.add_parser("canon", help="riscrive un pacchetto in forma canonica")
    _add_package(canon)
    _add_output(canon)
    canon.add_argument("--document", metavar="ID", help="identificatore da scrivere nel manifesto")
    canon.add_argument(
        "--base-version", metavar="IMPRONTA", help="versione di partenza da scrivere nel manifesto"
    )
    canon.add_argument(
        "--files-dir", metavar="CARTELLA", help="scrive anche i file canonici uno per uno qui"
    )
    _add_json(canon)
    canon.set_defaults(handler=_cmd_draft)

    build = commands.add_parser("build", help="produce LaTeX o PDF da un pacchetto")
    _add_package(build)
    _add_output(build)
    build.add_argument(
        "--format", choices=("pdf", "latex"), default="pdf", help="formato d'uscita (pdf)"
    )
    build.add_argument("--header", metavar="FILE", help="intestazione in JSON fornita da Rego")
    build.add_argument("--theme", metavar="CARTELLA", help="cartella di un tema esterno")
    _add_json(build)
    build.set_defaults(handler=_cmd_draft)

    upgrade = commands.add_parser("upgrade", help="porta un pacchetto alla grammatica corrente")
    _add_package(upgrade)
    _add_output(upgrade)
    _add_json(upgrade)
    upgrade.set_defaults(handler=_cmd_draft)

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


# Comandi che leggono un pacchetto. Con --json ogni comando risponde a ogni uscita con almeno
# il rapporto minimo (contratto, §4), salvo quando stdout è chiuso.
PACKAGE_COMMANDS = ("validate", "canon", "build", "upgrade")
COMMANDS = ("info", *PACKAGE_COMMANDS)


def _problem(code: str, message: str) -> dict[str, object]:
    return {
        "severity": "error",
        "code": code,
        "message": message,
        "file": "",
        "line": 0,
        "column": 0,
    }


# Limiti in vigore per il comando in corso; null finché non sono applicati.
_ACTIVE: dict[str, int | None] = {"time_seconds": None, "memory_bytes": None}


def _payload(
    command: str | None,
    exit_code: ExitCode,
    *,
    errors: Sequence[dict[str, object]] = (),
    warnings: Sequence[dict[str, object]] = (),
) -> dict[str, object]:
    """Il rapporto minimo del contratto (§4), stabile fra le sue versioni."""
    return {
        "contract": declaration.CONTRACT_VERSION,
        "engine": {"name": declaration.ENGINE_NAME, "version": __version__},
        "command": command,
        "exit_code": int(exit_code),
        "ok": exit_code is ExitCode.OK,
        "errors": list(errors),
        "warnings": list(warnings),
        # I limiti di risorse davvero in vigore durante il comando (contratto, §4.1).
        "limits_active": dict(_ACTIVE),
    }


def _finish(
    wants_json: bool, command: str | None, exit_code: ExitCode, code: str, message: str
) -> ExitCode:
    """Chiude con un solo errore: rapporto JSON se richiesto, altrimenti un messaggio."""
    if wants_json:
        with contextlib.suppress(OSError, ValueError):
            _write_json(_payload(command, exit_code, errors=[_problem(code, message)]))
    _note(f"regodoc: {message}\n")
    return exit_code


def _cmd_draft(args: argparse.Namespace) -> ExitCode:
    # Un comando non ancora implementato è un limite di questa versione del motore, cioè
    # dell'ambiente, non del pacchetto né della riga di comando.
    message = f"il comando «{args.command}» non è ancora disponibile in questa versione del motore"
    if args.json:
        _write_json(
            _payload(
                args.command,
                ExitCode.ENVIRONMENT,
                errors=[_problem("regodoc.not_implemented", message)],
            )
        )
        return ExitCode.ENVIRONMENT
    _write(sys.stderr, f"regodoc: {message}\n")
    return ExitCode.ENVIRONMENT


def _report(command: str, args: argparse.Namespace, validation: Validation) -> ExitCode:
    """Scrive il rapporto e sceglie il codice d'uscita (0, oppure 1 con errori o --strict)."""
    collector = validation.report
    failed = collector.has_errors() or (args.strict and bool(collector.strict_warnings))
    code = ExitCode.REFUSED if failed else ExitCode.OK
    if args.json:
        payload = _payload(
            command,
            code,
            errors=[d.to_json() for d in collector.errors],
            warnings=[d.to_json() for d in collector.warnings],
        )
        payload["input"] = (
            {"sha256": validation.input_sha256, "bytes": validation.input_bytes}
            if validation.input_sha256 is not None
            else None
        )
        payload.update(validation.summary())
        payload["warnings_omitted"] = collector.warnings_omitted
        _write_json(payload)
    else:
        for diagnostic in collector.items:
            prefix = {Severity.ERROR: "errore", Severity.WARNING: "avviso"}.get(
                diagnostic.severity, "nota"
            )
            _write(sys.stderr, f"{prefix}: {diagnostic}\n")
        errors, warnings = len(collector.errors), len(collector.warnings)
        verdict = "pacchetto rifiutato" if failed else "pacchetto valido"
        _write(sys.stderr, f"regodoc: {verdict} ({errors} errori, {warnings} avvisi)\n")
    return code


def _cmd_validate(args: argparse.Namespace) -> ExitCode:
    path = Path(args.package)
    if not path.exists():
        return _finish(
            args.json,
            "validate",
            ExitCode.USAGE,
            "regodoc.usage",
            f"il pacchetto «{clip(args.package)}» non esiste",
        )
    mode = path.stat().st_mode
    if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
        # Una FIFO o un dispositivo lascerebbero il motore in attesa senza fine.
        return _finish(
            args.json,
            "validate",
            ExitCode.USAGE,
            "regodoc.usage",
            f"«{clip(args.package)}» non è né un file regolare né una cartella",
        )
    try:
        validation = validate_package(path)
    except PermissionError:
        return _finish(
            args.json,
            "validate",
            ExitCode.ENVIRONMENT,
            "regodoc.environment",
            f"non posso leggere «{clip(args.package)}»: permesso negato",
        )
    return _report("validate", args, validation)


def main(argv: Sequence[str] | None = None) -> int:
    """Esegue il comando e restituisce il codice d'uscita."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    _ACTIVE.update(time_seconds=None, memory_bytes=None)
    wants_json = "--json" in arguments
    command = next((a for a in arguments if a in COMMANDS), None)
    parser = build_parser()
    try:
        args = parser.parse_args(arguments)
        if args.contract is not None and args.contract not in declaration.CONTRACTS:
            supported = ", ".join(str(v) for v in declaration.CONTRACTS)
            return int(
                _finish(
                    wants_json,
                    command,
                    ExitCode.USAGE,
                    "regodoc.usage",
                    f"questo motore non supporta il contratto {args.contract}; "
                    f"supporta: {supported}",
                )
            )
        if args.max_seconds is not None and args.max_seconds < 1:
            return int(
                _finish(
                    wants_json,
                    command,
                    ExitCode.USAGE,
                    "regodoc.usage",
                    "--max-seconds vuole un numero intero di secondi, almeno 1",
                )
            )
        with limits.applied(args.command, args.max_seconds) as active:
            _ACTIVE.update(active)
            return int(args.handler(args))
    except UsageExit as exit_:
        # Errore della riga di comando: argparse ha già scritto uso e messaggio su stderr. Il
        # rapporto c'è anche senza comando, con «command» a null (contratto, §4.1).
        if wants_json:
            with contextlib.suppress(OSError, ValueError):
                _write_json(
                    _payload(
                        command, ExitCode.USAGE, errors=[_problem("regodoc.usage", exit_.message)]
                    )
                )
        return int(ExitCode.USAGE)
    except SystemExit as exit_:
        # argparse esce con SystemExit anche per l'aiuto e la versione.
        return exit_.code if isinstance(exit_.code, int) else int(ExitCode.USAGE)
    except limits.TimeLimitExceeded as exceeded:
        return int(
            _finish(
                wants_json,
                command,
                ExitCode.ENVIRONMENT,
                "regodoc.limit.time",
                f"tempo massimo superato ({exceeded.seconds} s); non ritentare con lo stesso "
                "pacchetto",
            )
        )
    except KeyboardInterrupt:
        return int(
            _finish(wants_json, command, ExitCode.INTERRUPTED, "regodoc.interrupted", "interrotto")
        )
    except BrokenPipeError:
        # Chi legge l'uscita ha chiuso la pipe: è un fatto d'ambiente, non un difetto. Il
        # rapporto non ha più dove andare.
        _silence_stdout()
        _note("regodoc: errore d'ambiente: l'uscita è stata chiusa prima della fine\n")
        return int(ExitCode.ENVIRONMENT)
    except MemoryError:
        # La memoria concessa al processo non basta per questo pacchetto: è un limite
        # dell'ambiente, non un difetto del motore, e ritentare con lo stesso pacchetto non
        # serve (contratto, §2.3).
        return int(
            _finish(
                wants_json,
                command,
                ExitCode.ENVIRONMENT,
                "regodoc.limit.memory",
                "memoria esaurita: il pacchetto chiede più memoria di quella concessa al "
                "motore; non ritentare con lo stesso pacchetto",
            )
        )
    except OSError as error:
        return int(
            _finish(
                wants_json,
                command,
                ExitCode.ENVIRONMENT,
                "regodoc.environment",
                f"errore d'ambiente: {error.strerror or type(error).__name__}",
            )
        )
    except Exception as error:
        return int(
            _finish(
                wants_json,
                command,
                ExitCode.INTERNAL,
                "regodoc.internal",
                f"errore interno del motore ({type(error).__name__}); "
                "è un difetto del motore, non del pacchetto",
            )
        )
