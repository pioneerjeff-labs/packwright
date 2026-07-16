import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

from packwright import __version__
from packwright.adapters import compile_adapter_pack
from packwright.checker import score_mechanism
from packwright.core.adapter_layout import supported_adapters
from packwright.core.pack_metadata import SPEC_PATH, embed_pack_metadata, load_embedded_spec
from packwright.core import (
    PackwrightError,
    adopt_existing,
    apply_adoption_review,
    apply_migration,
    create_handoff,
    doctor_target,
    generate_character_source,
    generate_character_source_from_data,
    install_pack,
    load_character_intake,
    load_mechanism,
    normalize_mechanism,
    plan_migration,
    plan_adoption_review,
    refresh_emotion_engine,
    render_interviewer_prompt,
    resolve_mechanism,
    starter_character_intake,
    starter_character_preset,
    starter_character_preset_names,
    validate_mechanism,
    write_interviewer_prompt,
)
from packwright.core.emotion_engine_contract import emotion_engine_artifacts
from packwright.core.errors import PackwrightValidationError
from packwright.core.locale import normalize_locale
from packwright.core.naming import normalize_slug
from packwright.core.path_safety import resolve_destination_path, resolve_source_path


ADAPTER_CHOICES = supported_adapters()


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "validate":
            return _cmd_validate(args)
        if args.command == "resolve":
            return _cmd_resolve(args)
        if args.command == "compile":
            return _cmd_compile(args)
        if args.command == "score":
            return _cmd_score(args)
        if args.command == "install":
            return _cmd_install(args)
        if args.command in {"migrate", "migrate-target"}:
            return _cmd_migrate_target(args)
        if args.command == "handoff-export":
            return _cmd_handoff_export(args)
        if args.command == "adopt":
            return _cmd_adopt(args)
        if args.command in {"refresh-emotion-engine", "refresh-emotion-engine-codex"}:
            return _cmd_refresh_emotion_engine(args)
        if args.command == "doctor":
            return _cmd_doctor(args)
        if args.command == "draft-character":
            return _cmd_draft_character(args)
        if args.command == "presets":
            return _cmd_presets(args)
        if args.command == "new":
            return _cmd_new(args)
        if args.command in {"init", "init-character"}:
            return _cmd_init_character(args)
        if args.command in {"build", "run"}:
            return _cmd_run(args)
    except PackwrightError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 1


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="packwright",
        description="Compile, install, migrate, check, and repair portable agent packs.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
        metavar="{new,init,draft-character,presets,adopt,build,install,migrate,doctor,score}",
    )

    new = subparsers.add_parser(
        "new",
        help="create, build, and install a fresh agent while preserving source and pack directories",
    )
    _add_new_arguments(new)

    init_cmd = subparsers.add_parser(
        "init",
        help="create editable agent source from your intake or a nameless starter preset",
    )
    _add_init_arguments(init_cmd)

    presets = subparsers.add_parser(
        "presets",
        help="list or inspect the exact defaults for nameless starter presets",
    )
    presets.add_argument(
        "preset",
        nargs="?",
        choices=starter_character_preset_names(),
        help="optional preset to inspect in full",
    )
    presets.add_argument("--out", help="output preset JSON path")

    build = subparsers.add_parser("build", help="validate, compile, and score an adapter pack")
    _add_build_arguments(build)

    validate = subparsers.add_parser("validate", description="validate a character mechanism spec")
    validate.add_argument("mechanism")

    resolve = subparsers.add_parser("resolve", description="resolve a character mechanism spec to JSON")
    resolve.add_argument("mechanism")
    resolve.add_argument("--set", action="append", default=[], dest="sets", help="parameter override as key=value")
    resolve.add_argument("--out", help="output JSON path")

    compile_cmd = subparsers.add_parser("compile", description="compile an adapter pack")
    compile_cmd.add_argument("mechanism")
    compile_cmd.add_argument("--adapter", default="codex", choices=ADAPTER_CHOICES)
    compile_cmd.add_argument("--set", action="append", default=[], dest="sets", help="parameter override as key=value")
    compile_cmd.add_argument("--out-dir", default="build/codex", help="adapter pack output directory")
    compile_cmd.add_argument("--force", action="store_true", help="overwrite existing pack artifacts")

    install = subparsers.add_parser("install", help="install an adapter pack into a local runtime directory")
    install.add_argument("pack_dir_positional", nargs="?", metavar="PACK_DIR", help="adapter pack directory")
    install.add_argument(
        "--adapter",
        choices=ADAPTER_CHOICES,
        help="optional assertion; defaults to the adapter declared by the pack manifest",
    )
    install.add_argument(
        "--pack-dir",
        dest="pack_dir_option",
        metavar="PACK_DIR",
        help="existing adapter pack directory",
    )
    install.add_argument(
        "--target-dir",
        "--target",
        required=True,
        dest="target_dir",
        metavar="TARGET",
        help="local runtime working directory",
    )
    install.add_argument(
        "--force",
        action="store_true",
        help="overwrite managed target artifacts while preserving portable state",
    )
    install.add_argument(
        "--include-emotion-engine",
        action="store_true",
        default=None,
        help="include the optional adapter-native Emotion Engine v1.0.0 runtime and project MCP configuration",
    )
    install.add_argument(
        "--emotion-engine-source",
        help="Emotion Engine v1.0.0 repository root or integration directory",
    )
    install.add_argument(
        "--include-emotion-engine-codex",
        action="store_true",
        default=None,
        help=argparse.SUPPRESS,
    )
    install.add_argument(
        "--emotion-engine-codex-source",
        help=argparse.SUPPRESS,
    )
    install.add_argument(
        "--emotion-style",
        help="style description for the initialized Emotion Engine state",
    )
    install.add_argument(
        "--emotion-engine-mode",
        default=None,
        choices=["light", "always", "paused"],
        help="override the pack's recommended Emotion Engine runtime mode",
    )
    install.add_argument("--out", help="output install JSON path")

    migrate = subparsers.add_parser("migrate", help="migrate an installed target into another adapter")
    _add_migrate_arguments(migrate)

    migrate_target = subparsers.add_parser(
        "migrate-target",
        description="legacy alias for migrate",
    )
    _add_migrate_arguments(migrate_target)

    handoff = subparsers.add_parser(
        "handoff-export",
        description="write a reviewable handoff file for another agent",
    )
    handoff.add_argument("--source-target-dir", required=True, help="installed source target directory")
    handoff.add_argument("--out", required=True, help="handoff Markdown output path")
    handoff.add_argument("--summary", help="human handoff summary written by the source agent")
    handoff.add_argument("--changed", action="append", default=[], help="relative source target path changed in this handoff")
    handoff.add_argument("--read", action="append", default=[], dest="reads", help="relative source target path the receiver should read")
    handoff.add_argument("--next-step", action="append", default=[], help="next step for the receiving agent")
    handoff.add_argument(
        "--include-inventory",
        action="store_true",
        help="include a portable memory/workspace file inventory for review; does not copy files",
    )

    adopt = subparsers.add_parser(
        "adopt",
        help="inventory an existing agent for reviewable adoption",
        description="inventory an existing local agent/workspace for reviewable Packwright adoption",
    )
    adopt_source = adopt.add_mutually_exclusive_group(required=True)
    adopt_source.add_argument("--from", dest="source_dir", help="existing local instance directory")
    adopt_source.add_argument("--review", help="reviewed adoption-review.yaml to plan or apply")
    adopt.add_argument("--target-dir", help="directory where adoption report and scaffold should be written")
    adopt.add_argument("--dry-run", action="store_true", help="only print inventory, queue, or reviewed action plan")
    adopt.add_argument("--yes", action="store_true", help="apply approved review decisions without an interactive prompt")
    adopt.add_argument("--force", action="store_true", help="overwrite existing adoption report files")
    adopt.add_argument("--out", help="output adopt JSON path")

    refresh_emotion = subparsers.add_parser(
        "refresh-emotion-engine",
        description="refresh an installed Emotion Engine runtime without resetting live state",
    )
    _add_refresh_emotion_arguments(refresh_emotion)
    refresh_emotion_legacy = subparsers.add_parser(
        "refresh-emotion-engine-codex",
        description="deprecated alias for refresh-emotion-engine",
    )
    _add_refresh_emotion_arguments(refresh_emotion_legacy)

    doctor = subparsers.add_parser("doctor", help="inspect and optionally repair an installed target")
    doctor.add_argument("target_dir_positional", nargs="?", metavar="TARGET", help="installed target directory")
    doctor.add_argument(
        "--target-dir",
        "--target",
        dest="target_dir_option",
        metavar="TARGET",
        help="installed target directory",
    )
    doctor.add_argument("--fix", action="store_true", help="apply deterministic repairs for detected drift")
    doctor.add_argument(
        "--emotion-engine-source",
        help="Emotion Engine v1.0.0 repository root or integration directory, required to refresh runtime drift",
    )
    doctor.add_argument(
        "--emotion-engine-codex-source",
        help=argparse.SUPPRESS,
    )
    doctor.add_argument(
        "--emotion-style",
        help="style description used only if the target state file must be initialized",
    )
    doctor.add_argument(
        "--emotion-engine-mode",
        default=None,
        choices=["light", "always", "paused"],
        help="override the target manifest's Emotion Engine runtime mode when fixing",
    )
    doctor.add_argument("--out", help="output doctor JSON path")

    score = subparsers.add_parser("score", help="score a resolved mechanism and adapter pack")
    score.add_argument("mechanism", help="mechanism source, pack, or installed target")
    score.add_argument("--adapter", default="codex", choices=ADAPTER_CHOICES)
    score.add_argument("--pack-dir", help="existing adapter pack directory; compiles in memory when omitted")
    score.add_argument("--threshold", type=int, help="score threshold override")
    score.add_argument("--set", action="append", default=[], dest="sets", help="parameter override as key=value")
    score.add_argument("--out", help="output score JSON path")

    draft_character = subparsers.add_parser(
        "draft-character",
        help="draft a custom character intake through your coding agent",
        description="print the LLM interviewer contract for drafting canonical character_intake.yaml",
    )
    draft_character.add_argument("--user-name", default="the user", help="default user name in the interview contract")
    draft_character.add_argument("--prompt-out", help="write the interviewer prompt to this Markdown file")

    init_character = subparsers.add_parser(
        "init-character",
        description="legacy alias for init",
    )
    _add_init_arguments(init_character)

    run = subparsers.add_parser("run", description="legacy alias for build")
    _add_build_arguments(run)

    return parser


def _add_refresh_emotion_arguments(parser):
    parser.add_argument("--target-dir", required=True, help="installed target directory")
    parser.add_argument(
        "--emotion-engine-source",
        help="Emotion Engine v1.0.0 repository root or integration directory",
    )
    parser.add_argument(
        "--emotion-engine-codex-source",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--emotion-style",
        help="style description used only if the target state file must be initialized",
    )
    parser.add_argument(
        "--emotion-engine-mode",
        default=None,
        choices=["light", "always", "paused"],
        help="override the target manifest's Emotion Engine runtime mode",
    )
    parser.add_argument("--out", help="output refresh JSON path")


def _add_migrate_arguments(parser):
    parser.add_argument(
        "source_target_dir_positional",
        nargs="?",
        metavar="SOURCE_TARGET",
        help="installed source target directory",
    )
    parser.add_argument(
        "--source-target-dir",
        dest="source_target_dir_option",
        metavar="SOURCE_TARGET",
        help="installed source target directory",
    )
    parser.add_argument(
        "--target-dir",
        "--target",
        required=True,
        dest="target_dir",
        metavar="TARGET",
        help="destination runtime working directory",
    )
    parser.add_argument(
        "--to",
        "--to-adapter",
        required=True,
        dest="to_adapter",
        choices=ADAPTER_CHOICES,
    )
    parser.add_argument("--mechanism", help="source mechanism path; defaults to source manifest source_mechanism")
    parser.add_argument("--set", action="append", default=[], dest="sets", help="parameter override as key=value")
    parser.add_argument("--pack-dir", help="optional destination adapter pack output directory")
    parser.add_argument("--force", action="store_true", help="overwrite existing pack/target/migration state")
    execution = parser.add_mutually_exclusive_group()
    execution.add_argument(
        "--dry-run",
        action="store_true",
        help="print the complete migration plan without writing target or pack files",
    )
    execution.add_argument(
        "--yes",
        action="store_true",
        help="apply without an interactive confirmation prompt",
    )
    parser.add_argument("--json", action="store_true", help="emit the complete path-level migration receipt as JSON")
    parser.add_argument("--slug", help="explicit character slug for generated destination artifacts")
    parser.add_argument(
        "--no-upgrade-adapter-support",
        action="store_false",
        dest="upgrade_adapter_support",
        help="do not synthesize missing current adapter declarations in old mechanism specs",
    )
    parser.add_argument(
        "--no-emotion-state",
        action="store_false",
        dest="include_emotion_state",
        help="do not carry any canonical or legacy Emotion Engine state snapshot",
    )
    parser.add_argument(
        "--emotion-engine-source",
        help="Emotion Engine v1.0.0 source used to activate the carried state in the destination adapter",
    )
    parser.add_argument(
        "--emotion-engine-codex-source",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--emotion-style",
        help="style description used only if a destination state file must be initialized",
    )
    parser.add_argument(
        "--emotion-engine-mode",
        default=None,
        choices=["light", "always", "paused"],
        help="override the destination Emotion Engine runtime mode",
    )
    parser.add_argument("--out", help="output migration JSON path")


def _add_init_arguments(parser):
    parser.add_argument("intake", nargs="?", help="character_intake.yaml path; omit with --template or --interactive")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="basic fallback prompts only; prefer draft-character with an LLM for semantic normalization",
    )
    parser.add_argument(
        "--template",
        choices=starter_character_preset_names(),
        help="nameless starter preset: code, work, or companion; requires --name",
    )
    parser.add_argument("--name", help="character name chosen by the user; required with --template")
    parser.add_argument("--user-name", help="how the character should refer to the user in generated files")
    parser.add_argument("--slug", help="explicit lowercase ASCII character slug, useful for non-Latin names")
    parser.add_argument(
        "--locale",
        help="compiler boilerplate locale for --template or --interactive; en and zh-CN are supported, others fall back to en",
    )
    parser.add_argument("--save-intake", help="write the generated or answered intake YAML to this path")
    parser.add_argument(
        "-o",
        "--out-dir",
        dest="out_dir",
        help="output source directory; defaults to work/<character>",
    )
    parser.add_argument("--force", action="store_true", help="overwrite generated character files")
    parser.add_argument("--out", help="output generation JSON path")


def _add_new_arguments(parser):
    parser.add_argument("intake", nargs="?", help="confirmed CharacterIntake YAML; omit with --template or --interactive")
    parser.add_argument("--interactive", action="store_true", help="basic confirmed terminal fallback")
    parser.add_argument("--template", choices=starter_character_preset_names(), help="nameless starter preset")
    parser.add_argument("--accept-preset", action="store_true", help="confirm the selected preset defaults were reviewed before this one-shot build")
    parser.add_argument("--name", help="user-chosen character name; required with --template")
    parser.add_argument("--user-name", help="how the character should refer to the user")
    parser.add_argument("--slug", help="explicit lowercase ASCII character slug")
    parser.add_argument("--locale", help="compiler locale; en and zh-CN are supported, others fall back to en")
    parser.add_argument("--save-intake", help="write generated or interactive intake YAML to this path")
    parser.add_argument("--adapter", default="codex", choices=ADAPTER_CHOICES)
    parser.add_argument("--work-dir", help="editable source directory; defaults to work/<slug>")
    parser.add_argument("--pack-dir", help="built adapter pack directory; defaults to pack/<slug>-<adapter>")
    parser.add_argument("--target-dir", "--target", required=True, dest="target_dir", help="fresh installed target directory")
    parser.add_argument("--threshold", type=int, help="score threshold override")
    parser.add_argument("--include-emotion-engine", action="store_true", help="install Emotion Engine v1.0.0 and project MCP configuration")
    parser.add_argument("--emotion-engine-source", help="Emotion Engine v1.0.0 repository or integration directory")
    parser.add_argument("--emotion-style", help="style description for initialized Emotion Engine state")
    parser.add_argument("--emotion-engine-mode", choices=["light", "always", "paused"], help="override the recommended Emotion Engine mode")
    parser.add_argument("--out", help="output orchestration JSON path")


def _add_build_arguments(parser):
    parser.add_argument("mechanism")
    parser.add_argument("--adapter", default="codex", choices=ADAPTER_CHOICES)
    parser.add_argument("--set", action="append", default=[], dest="sets", help="parameter override as key=value")
    parser.add_argument(
        "-o",
        "--out-dir",
        "--build-dir",
        default="build/codex",
        dest="build_dir",
        help="adapter pack output directory",
    )
    parser.add_argument("--threshold", type=int, help="score threshold override")
    parser.add_argument("--force", action="store_true", help="overwrite existing pack artifacts")


def _cmd_validate(args):
    data = load_mechanism(args.mechanism)
    validate_mechanism(data)
    print("ok")
    return 0


def _cmd_resolve(args):
    data = load_mechanism(args.mechanism)
    resolved = resolve_mechanism(data, _parse_sets(args.sets))
    _write_json_or_print(resolved, args.out)
    return 0


def _cmd_compile(args):
    data = load_mechanism(args.mechanism)
    resolved = resolve_mechanism(data, _parse_sets(args.sets))
    pack = _compile_pack(args.adapter, resolved, {"source_mechanism": args.mechanism})
    receipt = score_mechanism(resolved, pack, adapter=args.adapter)
    pack = embed_pack_metadata(pack, resolved, receipt)
    out_dir = Path(args.out_dir)
    _write_pack(pack, out_dir, force=args.force)
    print(
        json.dumps(
            {
                "adapter_pack": str(out_dir),
                "artifacts": sorted(pack.keys()),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def _cmd_score(args):
    input_path = Path(args.mechanism)
    embedded_spec = input_path / SPEC_PATH
    is_embedded = input_path.is_dir() and embedded_spec.is_file()
    if is_embedded:
        data = load_embedded_spec(input_path)
        if not args.pack_dir:
            args.pack_dir = str(input_path)
        manifest = _load_pack_manifest(input_path)
        args.adapter = manifest.get("adapter", args.adapter)
    else:
        data = load_mechanism(args.mechanism)
    params = _parse_sets(args.sets)
    if args.pack_dir:
        pack = _read_pack(Path(args.pack_dir))
        if not params:
            params = _pack_resolved_parameters(pack)
    else:
        pack = None
    resolved = normalize_mechanism(data) if is_embedded and not params else resolve_mechanism(data, params)
    if pack is None:
        pack = _compile_pack(args.adapter, resolved, {"source_mechanism": args.mechanism})
    result = score_mechanism(resolved, pack, adapter=args.adapter, threshold=args.threshold)
    _write_json_or_print(result, args.out)
    return 0 if result["passed"] else 1


def _cmd_install(args):
    pack_dir = _required_path_argument(
        args.pack_dir_positional,
        args.pack_dir_option,
        "pack directory",
        "PACK_DIR or --pack-dir",
    )
    result = install_pack(
        pack_dir,
        args.target_dir,
        adapter=args.adapter,
        force=args.force,
        include_emotion_engine=args.include_emotion_engine,
        emotion_engine_source=args.emotion_engine_source,
        include_emotion_engine_codex=args.include_emotion_engine_codex,
        emotion_engine_codex_source=args.emotion_engine_codex_source,
        emotion_style=args.emotion_style,
        emotion_engine_mode=args.emotion_engine_mode,
    )
    _write_json_or_print(result, args.out)
    return 0


def _cmd_migrate_target(args):
    source_target_dir = _required_path_argument(
        args.source_target_dir_positional,
        args.source_target_dir_option,
        "source target",
        "SOURCE_TARGET or --source-target-dir",
    )
    plan = plan_migration(
        source_target_dir,
        args.target_dir,
        to_adapter=args.to_adapter,
        mechanism_path=args.mechanism,
        parameters=_parse_sets(args.sets),
        pack_dir=args.pack_dir,
        force=args.force,
        include_emotion_state=args.include_emotion_state,
        slug=args.slug,
        upgrade_adapter_support=args.upgrade_adapter_support,
        emotion_engine_source=args.emotion_engine_source,
        emotion_engine_codex_source=args.emotion_engine_codex_source,
        emotion_style=args.emotion_style,
        emotion_engine_mode=args.emotion_engine_mode,
    )
    report = plan.to_dict()
    if args.dry_run:
        report["dry_run"] = True
        _emit_migration_report(report, args)
        return 0 if report["ready"] else 1

    if not report["ready"]:
        report["dry_run"] = True
        _emit_migration_report(report, args)
        return 1

    if not args.yes:
        if args.json or not (sys.stdin.isatty() and sys.stdout.isatty()):
            report["status"] = "confirmation_required"
            report["dry_run"] = True
            _emit_migration_report(report, args)
            print(
                "migration not applied: use --dry-run to preview or --yes after review",
                file=sys.stderr,
            )
            return 2
        _print_migration_report(report)
        if not _confirm_migration():
            print("Migration cancelled. No files written.")
            return 1
    result = apply_migration(plan)
    result["dry_run"] = False
    _emit_migration_report(result, args)
    return 0 if result["ok"] else 1


def _cmd_handoff_export(args):
    result = create_handoff(
        args.source_target_dir,
        args.out,
        summary=args.summary,
        changed_paths=args.changed,
        recommended_reads=args.reads or None,
        next_steps=args.next_step,
        include_inventory=args.include_inventory,
    )
    _write_json_or_print(result, None)
    return 0


def _cmd_adopt(args):
    if args.review:
        if args.force:
            raise PackwrightError("adopt review apply never overwrites destinations; --force is not supported")
        if not args.target_dir:
            raise PackwrightError("--target-dir is required with --review")
        plan = plan_adoption_review(args.review, args.target_dir)
        if args.dry_run:
            _write_json_or_print(plan, args.out)
            return 0 if plan["ready"] else 1
        if not plan["ready"]:
            _write_json_or_print(plan, args.out)
            return 1
        if not args.yes and not (sys.stdin.isatty() and _confirm_adoption_apply(plan)):
            plan["status"] = "confirmation_required"
            _write_json_or_print(plan, args.out)
            return 2
        result = apply_adoption_review(args.review, args.target_dir)
        _write_json_or_print(result, args.out)
        return 0
    if args.yes:
        raise PackwrightError("--yes is only accepted with --review")
    dry_run = args.dry_run or not args.target_dir
    result = adopt_existing(
        args.source_dir,
        target_dir=args.target_dir,
        dry_run=dry_run,
        force=args.force,
    )
    _write_json_or_print(result, args.out)
    return 0


def _confirm_adoption_apply(plan):
    answer = input(f"Apply {plan['approved']} reviewed adoption decisions? [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def _cmd_refresh_emotion_engine(args):
    source = args.emotion_engine_source or args.emotion_engine_codex_source
    result = refresh_emotion_engine(
        args.target_dir,
        emotion_engine_source=source,
        emotion_style=args.emotion_style,
        emotion_engine_mode=args.emotion_engine_mode,
    )
    _write_json_or_print(result, args.out)
    return 0


def _cmd_doctor(args):
    target_dir = _required_path_argument(
        args.target_dir_positional,
        args.target_dir_option,
        "target",
        "TARGET or --target-dir",
    )
    result = doctor_target(
        target_dir,
        fix=args.fix,
        emotion_engine_source=args.emotion_engine_source,
        emotion_engine_codex_source=args.emotion_engine_codex_source,
        emotion_style=args.emotion_style,
        emotion_engine_mode=args.emotion_engine_mode,
    )
    _write_json_or_print(result, args.out)
    return 0 if result.get("ok") else 1


def _cmd_draft_character(args):
    if args.prompt_out:
        path = write_interviewer_prompt(args.prompt_out, user_name=args.user_name)
        print(json.dumps({"interviewer_prompt": str(path)}, indent=2, sort_keys=True))
    else:
        print(render_interviewer_prompt(user_name=args.user_name))
    return 0


def _cmd_presets(args):
    if args.preset:
        result = starter_character_preset(args.preset)
    else:
        result = {
            "kind": "StarterCharacterPresetCatalog",
            "presets": [
                starter_character_preset(name)
                for name in starter_character_preset_names()
            ],
        }
    _write_json_or_print(result, args.out)
    return 0


def _cmd_new(args):
    selected = sum(bool(item) for item in (args.intake, args.template, args.interactive))
    if selected != 1:
        raise PackwrightError("new requires exactly one confirmed intake path, --template, or --interactive")
    if args.template:
        if not args.name:
            raise PackwrightError("starter presets are nameless; provide the character name with --name")
        if not args.accept_preset:
            raise PackwrightError(
                "one-shot preset creation requires --accept-preset after reviewing `packwright presets <name>`"
            )
        intake = starter_character_intake(
            args.template,
            name=args.name,
            user_name=args.user_name,
            slug=args.slug,
            locale=args.locale,
        )
        creation_mode = "accepted_preset"
    elif args.interactive:
        if args.name or args.accept_preset:
            raise PackwrightError("--name and --accept-preset are only accepted with --template")
        print(
            "warning: --interactive is a basic fallback and does not semantically normalize answers; "
            "prefer `packwright draft-character` with an LLM-produced intake YAML.",
            file=sys.stderr,
        )
        intake = _prompt_character_intake(args.user_name, slug=args.slug, locale=args.locale)
        print("\nCanonical CharacterIntake preview:\n")
        print(yaml.safe_dump(intake, sort_keys=False, allow_unicode=True), end="")
        if not _confirm_character_intake():
            print("Character creation cancelled. No files written.")
            return 1
        creation_mode = "interactive_confirmed"
    else:
        if args.name or args.user_name or args.slug or args.locale or args.accept_preset:
            raise PackwrightError(
                "name, user-name, slug, locale, and preset acceptance belong in the confirmed intake YAML"
            )
        if args.save_intake:
            raise PackwrightError("--save-intake is only used with --template or --interactive")
        intake = load_character_intake(args.intake)
        creation_mode = "confirmed_intake"

    slug = normalize_slug(intake["character"].get("slug") or intake["character"]["name"])
    work_dir = Path(args.work_dir) if args.work_dir else Path("work") / slug
    pack_dir = Path(args.pack_dir) if args.pack_dir else Path("pack") / f"{slug}-{args.adapter}"
    target_dir = Path(args.target_dir)
    _assert_fresh_new_paths(work_dir, pack_dir, target_dir, args.save_intake)

    if args.save_intake:
        _write_yaml(intake, Path(args.save_intake))
    source = generate_character_source_from_data(intake, out_dir=work_dir)
    mechanism_path = Path(source["mechanism"])
    resolved = resolve_mechanism(load_mechanism(mechanism_path))
    resolved_path = pack_dir / "resolved.json"
    score_path = pack_dir / "score.json"
    pack = _compile_pack(
        args.adapter,
        resolved,
        {
            "source_mechanism": str(mechanism_path),
            "resolved_mechanism": str(resolved_path),
            "checker_score": str(score_path),
        },
    )
    score = score_mechanism(resolved, pack, adapter=args.adapter, threshold=args.threshold)
    pack = embed_pack_metadata(pack, resolved, score)
    outputs = dict(pack)
    outputs["resolved.json"] = pack[SPEC_PATH]
    outputs["score.json"] = json.dumps(score, indent=2, sort_keys=True) + "\n"
    _write_pack(outputs, pack_dir)

    report = {
        "kind": "FreshAgentCreation",
        "status": "built" if not score["passed"] else "ready_to_install",
        "creation_mode": creation_mode,
        "adapter": args.adapter,
        "source": source,
        "build": {
            "adapter_pack": str(pack_dir),
            "checker_score": str(score_path),
            "passed": score["passed"],
            "score": score["score"],
        },
    }
    if not score["passed"]:
        report["next_actions"] = [
            {"action": "review_score", "path": str(score_path)},
            {"action": "fix_source", "path": str(work_dir)},
        ]
        _write_json_or_print(report, args.out)
        return 1

    installed = install_pack(
        pack_dir,
        target_dir,
        adapter=args.adapter,
        include_emotion_engine=args.include_emotion_engine or None,
        emotion_engine_source=args.emotion_engine_source,
        emotion_style=args.emotion_style,
        emotion_engine_mode=args.emotion_engine_mode,
    )
    report.update(
        {
            "status": "installed",
            "install": installed,
            "next_actions": [
                {"action": "doctor", "command": f"packwright doctor {target_dir}"},
                {"action": "score", "command": f"packwright score {target_dir}"},
            ],
        }
    )
    _write_json_or_print(report, args.out)
    return 0


def _assert_fresh_new_paths(work_dir, pack_dir, target_dir, save_intake):
    named_paths = {"work": work_dir, "pack": pack_dir, "target": target_dir}
    for label, path in named_paths.items():
        if path.exists():
            raise PackwrightError(f"new requires a fresh {label} path; already exists: {path}")
    resolved = {label: path.resolve(strict=False) for label, path in named_paths.items()}
    pairs = (("work", "pack"), ("work", "target"), ("pack", "target"))
    for left, right in pairs:
        if resolved[left] == resolved[right] or resolved[left] in resolved[right].parents or resolved[right] in resolved[left].parents:
            raise PackwrightError(f"new work, pack, and target paths must not overlap: {left} and {right}")
    if save_intake and Path(save_intake).exists():
        raise PackwrightError(f"new will not overwrite an existing intake: {save_intake}")


def _cmd_init_character(args):
    if args.template:
        if args.intake:
            raise PackwrightError("init accepts either an intake path or --template, not both")
        if args.interactive:
            raise PackwrightError("init accepts either --interactive or --template, not both")
        if not args.name:
            raise PackwrightError("starter presets are nameless; provide the character name with --name")
        intake = starter_character_intake(
            args.template,
            name=args.name,
            user_name=args.user_name,
            slug=args.slug,
            locale=args.locale,
        )
        if args.save_intake:
            _write_yaml(intake, Path(args.save_intake))
        result = generate_character_source_from_data(intake, out_dir=args.out_dir, force=args.force)
        result["intake"] = args.save_intake or f"template:{args.template}"
        result["creation_mode"] = "preset"
        result["preset"] = args.template
        result["review"] = {
            "required_before": "build",
            "message": "Review and confirm the preset-derived character summary before building an adapter pack.",
            "editable_files": [
                "mechanism.yaml",
                "identity/persona.md",
                "identity/relationship.md",
                "identity/voice.md",
                "operating/boundaries.md",
            ],
        }
        result["next_actions"] = [
            {
                "action": "review_character",
                "required": True,
                "source": "character_summary",
            },
            {
                "action": "build",
                "run_after": "the user confirms or edits the preset-derived character",
            },
        ]
    elif args.interactive:
        if args.name:
            raise PackwrightError("--name is only accepted with --template; interactive mode asks for a name")
        print(
            "warning: --interactive is a basic fallback and does not semantically normalize answers; "
            "prefer `packwright draft-character` with an LLM-produced intake YAML.",
            file=sys.stderr,
        )
        intake = _prompt_character_intake(args.user_name, slug=args.slug, locale=args.locale)
        print("\nCanonical CharacterIntake preview:\n")
        print(yaml.safe_dump(intake, sort_keys=False, allow_unicode=True), end="")
        if not _confirm_character_intake():
            print("Character creation cancelled. No files written.")
            return 1
        if args.save_intake:
            _write_yaml(intake, Path(args.save_intake))
        result = generate_character_source_from_data(intake, out_dir=args.out_dir, force=args.force)
        result["intake"] = args.save_intake or "interactive"
        result["creation_mode"] = "interactive"
        result["intake_confirmed"] = True
    else:
        if args.name:
            raise PackwrightError("--name is only accepted with --template; intake files already contain a name")
        if not args.intake:
            raise PackwrightError("init requires an intake path unless --template or --interactive is used")
        if args.locale:
            raise PackwrightError("put locale in the intake YAML when initializing from a file")
        result = generate_character_source(args.intake, out_dir=args.out_dir, force=args.force)
    _write_json_or_print(result, args.out)
    return 0


def _cmd_run(args):
    data = load_mechanism(args.mechanism)
    validate_mechanism(data)
    resolved = resolve_mechanism(data, _parse_sets(args.sets))

    build_dir = Path(args.build_dir)
    resolved_path = build_dir / "resolved.json"
    score_path = build_dir / "score.json"

    pack = _compile_pack(
        args.adapter,
        resolved,
        {
            "source_mechanism": args.mechanism,
            "resolved_mechanism": str(resolved_path),
            "checker_score": str(score_path),
        },
    )
    result = score_mechanism(resolved, pack, adapter=args.adapter, threshold=args.threshold)

    pack = embed_pack_metadata(pack, resolved, result)

    outputs = dict(pack)
    outputs["resolved.json"] = pack[SPEC_PATH]
    outputs["score.json"] = json.dumps(result, indent=2, sort_keys=True) + "\n"
    _write_pack(outputs, build_dir, force=args.force)

    manifest = {
        "adapter_pack": str(build_dir),
        "resolved_mechanism": str(resolved_path),
        "checker_score": str(score_path),
        "passed": result["passed"],
        "score": result["score"],
    }
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


def _parse_sets(items):
    parsed = {}
    for item in items:
        if "=" not in item:
            raise PackwrightError(f"--set value must use key=value format: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise PackwrightError("--set key cannot be empty")
        parsed[key] = value
    return parsed


def _required_path_argument(positional, option, label, usage):
    if positional and option:
        raise PackwrightError(f"pass {label} once, using {usage}")
    value = option or positional
    if not value:
        raise PackwrightError(f"{label} is required; pass {usage}")
    return value


def _prompt_character_intake(user_name, slug=None, locale=None):
    print("Packwright character intake")
    print("Basic fallback mode: fixed questions, no LLM normalization.")
    name = _prompt_required("1. What should the character be called?")
    resolved_slug = normalize_slug(slug, default="") if slug else _prompt_optional_slug(name)
    relationship = _prompt_required(
        "2. What relationship should they have with you? "
        "For example: work partner, secretary, coach, friendly companion, or researcher."
    )
    primary_work = _prompt_list(
        "3. What should they mainly help you do? Separate multiple items with commas or semicolons."
    )
    voice = _prompt_required(
        "4. How should they sound? You can also describe tones or habits they should avoid."
    )
    continuity = _prompt_relationship_continuity()
    resolved_user_name = (
        user_name
        or os.environ.get("PACKWRIGHT_USER_NAME")
        or "the user"
    )

    return {
        "version": "0.1",
        "kind": "CharacterIntake",
        "locale": normalize_locale(locale),
        "character": {
            "name": name,
            "slug": resolved_slug or normalize_slug(name),
            "user_name": resolved_user_name,
            "relationship": relationship,
            "role": _role_from_answers(resolved_user_name, relationship, primary_work),
            "voice": voice,
            "avoid": _avoid_from_voice(voice),
            "primary_work": primary_work,
            "relationship_continuity": continuity,
            "traits": _traits_from_voice(voice),
            "direct_emotional_interaction": _direct_emotional_interaction_from_continuity(continuity),
        },
    }


def _prompt_optional_slug(name):
    value = input(
        "1b. Choose an English or romanized slug for filenames, such as nova. "
        "Leave blank to generate one automatically.\n> "
    ).strip()
    if value:
        return normalize_slug(value)
    return normalize_slug(name)


def _prompt_required(prompt):
    while True:
        value = input(prompt + "\n> ").strip()
        if value:
            return value
        print("This field is required.")


def _prompt_list(prompt):
    while True:
        value = _prompt_required(prompt)
        items = [item.strip() for item in re.split(r"[,，;；\n]+", value) if item.strip()]
        if items:
            return items
        print("Enter at least one item.")


def _prompt_relationship_continuity():
    prompt = (
        "5. How much relationship continuity should this character maintain?\n"
        "   A = Task-only, with no emotional relationship continuity\n"
        "   B = Warm, but remembers only important preferences\n"
        "   C = Close, long-term continuity that remembers interaction details"
    )
    choices = {
        "a": "task_only",
        "1": "task_only",
        "只做事": "task_only",
        "task_only": "task_only",
        "b": "warm_selective",
        "2": "warm_selective",
        "有温度": "warm_selective",
        "重要偏好": "warm_selective",
        "warm_selective": "warm_selective",
        "c": "close_continuous",
        "3": "close_continuous",
        "长期陪伴": "close_continuous",
        "持续记住": "close_continuous",
        "close_continuous": "close_continuous",
    }
    while True:
        value = input(prompt + "\n> ").strip().lower()
        if value in choices:
            return choices[value]
        print("Enter A, B, or C, or use task_only, warm_selective, or close_continuous.")


def _direct_emotional_interaction_from_continuity(continuity):
    return {
        "task_only": "work_only",
        "warm_selective": "some_direct_emotional_interaction",
        "close_continuous": "some_direct_emotional_interaction",
    }[continuity]


def _role_from_answers(user_name, relationship, primary_work):
    work = primary_work[0].rstrip(".")
    owner = "the user's" if user_name == "the user" else f"{user_name}'s"
    return f"{owner} {relationship} for {work}."


def _avoid_from_voice(voice):
    avoid = []
    lowered = voice.lower()
    for marker in ("讨厌", "不要", "not ", "avoid "):
        if marker in lowered:
            avoid.append(voice)
            break
    if not avoid:
        avoid = ["mechanical audit-log replies", "decorative warmth", "over-compliance"]
    return avoid


def _traits_from_voice(voice):
    traits = []
    for item in re.split(r"[,，;；、]+", voice):
        item = item.strip().lower().strip(".")
        if item and len(item) <= 32 and item not in traits:
            traits.append(item)
        if len(traits) == 4:
            break
    return traits or ["steady", "practical", "scope-preserving"]


def _compile_pack(adapter, resolved, references):
    try:
        return compile_adapter_pack(adapter, resolved, references=references)
    except ValueError as exc:
        raise PackwrightError(str(exc)) from exc


def _read_pack(pack_dir):
    manifest = _load_pack_manifest(pack_dir)
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PackwrightError("adapter pack manifest must contain a non-empty artifacts list")
    pack = {}
    for artifact in artifacts:
        path = resolve_source_path(pack_dir, artifact, "adapter pack artifact")
        pack[artifact] = path.read_text(encoding="utf-8")
    for artifact in _optional_installed_artifacts():
        path = pack_dir / artifact
        if path.exists():
            path = resolve_source_path(pack_dir, artifact, "optional installed artifact")
            pack[artifact] = path.read_text(encoding="utf-8")
    return pack


def _load_pack_manifest(pack_dir):
    try:
        manifest_path = resolve_source_path(pack_dir, "manifest.json", "adapter pack manifest")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PackwrightError(f"cannot read adapter pack manifest {pack_dir / 'manifest.json'}: {exc}")
    except json.JSONDecodeError as exc:
        raise PackwrightError(f"invalid adapter pack manifest {pack_dir / 'manifest.json'}: {exc}")
    if not isinstance(manifest, dict):
        raise PackwrightError(f"adapter pack manifest must be a mapping: {pack_dir / 'manifest.json'}")
    return manifest


def _optional_installed_artifacts():
    artifacts = set()
    for adapter in ADAPTER_CHOICES:
        artifacts.update(emotion_engine_artifacts(adapter))
    return tuple(sorted(artifacts))


def _pack_resolved_parameters(pack):
    try:
        manifest = json.loads(pack.get("manifest.json", "{}"))
    except json.JSONDecodeError:
        return {}
    params = manifest.get("resolved_parameters", {})
    return params if isinstance(params, dict) else {}


def _write_pack(pack, out_dir, force=False):
    destinations = {
        rel_path: resolve_destination_path(out_dir, rel_path, "pack artifact destination")
        for rel_path in pack
    }
    existing = [rel_path for rel_path, path in destinations.items() if path.exists()]
    if existing and not force:
        raise PackwrightValidationError([
            "pack directory already contains files that would be overwritten; rerun with --force after reviewing them",
            *[f"existing pack artifact: {artifact}" for artifact in sorted(existing)],
        ])
    for rel_path, content in pack.items():
        path = destinations[rel_path]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _emit_migration_report(report, args):
    if args.out:
        _write_json(report, Path(args.out))
        return
    if args.json or not sys.stdout.isatty():
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    _print_migration_report(report)


def _print_migration_report(report):
    source = report["source"]
    destination = report["destination"]
    print(f"Packwright migration {report['status']}: {source['adapter']} -> {destination['adapter']}")
    print(f"  {source['target_dir']} -> {destination['target_dir']}")
    for name in ("generated", "carried", "rewritten", "excluded"):
        items = report["changes"][name]
        print(f"  {name}: {len(items)} | {_migration_path_summary(items, exact=name == 'rewritten')}")
    planned = report["score"]["planned"]
    score_line = f"  score: planned {planned['score']:.1f} ({'pass' if planned['passed'] else 'fail'})"
    installed = report["score"].get("installed")
    if installed:
        score_line += f" | installed {installed['score']:.1f} ({'pass' if installed['passed'] else 'fail'})"
    integrity = report.get("integrity")
    if integrity:
        score_line += f" | hashes {integrity['checked']} ({'pass' if integrity['passed'] else 'fail'})"
    print(score_line)
    if report.get("conflicts"):
        print(f"  conflicts: {_migration_conflict_summary(report['conflicts'])}")
    if report["status"] != "applied":
        print("No files written. Use --json for the complete path-level receipt.")


def _migration_path_summary(items, exact=False):
    if not items:
        return "none"
    if exact:
        return ", ".join(item["path"] for item in items)
    groups = {}
    for item in items:
        path = item["path"]
        parts = Path(path).parts
        label = f"{parts[0]}/**" if len(parts) > 1 else path
        groups[label] = groups.get(label, 0) + 1
    return " | ".join(
        f"{label} ({count} files)" if label.endswith("/**") else label
        for label, count in sorted(groups.items())
    )


def _migration_conflict_summary(conflicts):
    groups = {}
    for item in conflicts:
        groups.setdefault(item["location"], []).append(item["path"])
    return " | ".join(
        f"{location}: {', '.join(paths)}"
        for location, paths in sorted(groups.items())
    )


def _confirm_migration():
    try:
        answer = input("Apply this migration? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _confirm_character_intake():
    try:
        answer = input("Create source from this CharacterIntake? [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _write_json_or_print(data, out):
    if out:
        _write_json(data, Path(out))
    else:
        print(json.dumps(data, indent=2, sort_keys=True))


def _write_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_yaml(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
