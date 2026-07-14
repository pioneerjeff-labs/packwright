import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

from packwright import __version__
from packwright.adapters import compile_to_claude_code_pack, compile_to_codex_pack, compile_to_cursor_pack
from packwright.checker import score_mechanism
from packwright.core.pack_metadata import SPEC_PATH, embed_pack_metadata, load_embedded_spec
from packwright.core import (
    PackwrightError,
    adopt_existing,
    apply_migration,
    create_handoff,
    doctor_target,
    generate_character_template,
    generate_character_template_from_data,
    install_pack,
    load_mechanism,
    plan_migration,
    refresh_emotion_engine_codex,
    render_interviewer_prompt,
    resolve_mechanism,
    starter_character_intake,
    starter_character_template_names,
    validate_mechanism,
    write_interviewer_prompt,
)
from packwright.core.emotion_engine_contract import EMOTION_ENGINE_CODEX_ARTIFACTS
from packwright.core.errors import PackwrightValidationError
from packwright.core.naming import normalize_slug
from packwright.core.path_safety import resolve_destination_path, resolve_source_path


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
        if args.command == "refresh-emotion-engine-codex":
            return _cmd_refresh_emotion_engine_codex(args)
        if args.command == "doctor":
            return _cmd_doctor(args)
        if args.command == "draft-character":
            return _cmd_draft_character(args)
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
        metavar="{init,build,install,migrate,doctor,score}",
    )

    init_cmd = subparsers.add_parser(
        "init",
        help="create an editable agent source from a starter template or intake file",
    )
    _add_init_arguments(init_cmd)

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
    compile_cmd.add_argument("--adapter", default="codex", choices=["codex", "claude-code", "cursor"])
    compile_cmd.add_argument("--set", action="append", default=[], dest="sets", help="parameter override as key=value")
    compile_cmd.add_argument("--out-dir", default="build/codex", help="adapter pack output directory")
    compile_cmd.add_argument("--force", action="store_true", help="overwrite existing pack artifacts")

    install = subparsers.add_parser("install", help="install an adapter pack into a local runtime directory")
    install.add_argument("pack_dir_positional", nargs="?", metavar="PACK_DIR", help="adapter pack directory")
    install.add_argument("--adapter", default="codex", choices=["codex", "claude-code", "cursor"])
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
        "--include-emotion-engine-codex",
        action="store_true",
        default=None,
        help="include the optional Emotion Engine Codex sidecar; requires --emotion-engine-codex-source or PACKWRIGHT_EMOTION_ENGINE_CODEX_DIR",
    )
    install.add_argument(
        "--emotion-engine-codex-source",
        help="source directory for the emotion-engine-codex sidecar skill",
    )
    install.add_argument(
        "--emotion-style",
        help="style description for the initialized Emotion Engine state",
    )
    install.add_argument(
        "--emotion-engine-mode",
        default=None,
        choices=["light", "always", "paused"],
        help="override the pack's recommended Emotion Engine runtime mode for Codex installs",
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
        description="inventory an existing local agent/workspace for reviewable Packwright adoption",
    )
    adopt.add_argument("--from", required=True, dest="source_dir", help="existing local instance directory")
    adopt.add_argument("--target-dir", help="directory where adoption report and scaffold should be written")
    adopt.add_argument("--dry-run", action="store_true", help="only print inventory and review queues")
    adopt.add_argument("--force", action="store_true", help="overwrite existing adoption report files")
    adopt.add_argument("--out", help="output adopt JSON path")

    refresh_emotion = subparsers.add_parser(
        "refresh-emotion-engine-codex",
        description="refresh an installed Codex Emotion Engine sidecar without resetting runtime state",
    )
    refresh_emotion.add_argument("--target-dir", required=True, help="installed Codex target directory")
    refresh_emotion.add_argument(
        "--emotion-engine-codex-source",
        help="source directory for the emotion-engine-codex sidecar skill",
    )
    refresh_emotion.add_argument(
        "--emotion-style",
        help="style description used only if the target state file must be initialized",
    )
    refresh_emotion.add_argument(
        "--emotion-engine-mode",
        default=None,
        choices=["light", "always", "paused"],
        help="override the target manifest's Emotion Engine runtime mode",
    )
    refresh_emotion.add_argument("--out", help="output refresh JSON path")

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
        "--emotion-engine-codex-source",
        help="source directory for the emotion-engine-codex sidecar skill",
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
    score.add_argument("--adapter", default="codex", choices=["codex", "claude-code", "cursor"])
    score.add_argument("--pack-dir", help="existing adapter pack directory; compiles in memory when omitted")
    score.add_argument("--threshold", type=int, help="score threshold override")
    score.add_argument("--set", action="append", default=[], dest="sets", help="parameter override as key=value")
    score.add_argument("--out", help="output score JSON path")

    draft_character = subparsers.add_parser(
        "draft-character",
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
        choices=["codex", "claude-code", "cursor"],
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
        help="do not copy .emotion-engine/codex-state.json as a migration snapshot",
    )
    parser.add_argument(
        "--emotion-engine-codex-source",
        help="source directory for the emotion-engine-codex sidecar skill when migrating to Codex",
    )
    parser.add_argument(
        "--emotion-style",
        help="style description used only if a Codex target state file must be initialized",
    )
    parser.add_argument(
        "--emotion-engine-mode",
        default=None,
        choices=["light", "always", "paused"],
        help="override the destination Codex target Emotion Engine runtime mode",
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
        choices=starter_character_template_names(),
        help="starter character template: productivity/system, creator/mira, or companion/lumen",
    )
    parser.add_argument("--user-name", help="how the character should refer to the user in generated files")
    parser.add_argument("--slug", help="explicit lowercase ASCII character slug, useful for non-Latin names")
    parser.add_argument("--save-intake", help="write the generated or answered intake YAML to this path")
    parser.add_argument(
        "-o",
        "--out-dir",
        dest="out_dir",
        help="output source directory; defaults to templates/<character>-work",
    )
    parser.add_argument("--force", action="store_true", help="overwrite generated character files")
    parser.add_argument("--out", help="output generation JSON path")


def _add_build_arguments(parser):
    parser.add_argument("mechanism")
    parser.add_argument("--adapter", default="codex", choices=["codex", "claude-code", "cursor"])
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
    resolved = data if is_embedded and not params else resolve_mechanism(data, params)
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
    dry_run = args.dry_run or not args.target_dir
    result = adopt_existing(
        args.source_dir,
        target_dir=args.target_dir,
        dry_run=dry_run,
        force=args.force,
    )
    _write_json_or_print(result, args.out)
    return 0


def _cmd_refresh_emotion_engine_codex(args):
    result = refresh_emotion_engine_codex(
        args.target_dir,
        emotion_engine_codex_source=args.emotion_engine_codex_source,
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


def _cmd_init_character(args):
    if args.template:
        if args.intake:
            raise PackwrightError("init accepts either an intake path or --template, not both")
        if args.interactive:
            raise PackwrightError("init accepts either --interactive or --template, not both")
        intake = starter_character_intake(args.template, user_name=args.user_name, slug=args.slug)
        if args.save_intake:
            _write_yaml(intake, Path(args.save_intake))
        result = generate_character_template_from_data(intake, out_dir=args.out_dir, force=args.force)
        result["intake"] = args.save_intake or f"template:{args.template}"
    elif args.interactive:
        print(
            "warning: --interactive is a basic fallback and does not semantically normalize answers; "
            "prefer `packwright draft-character` with an LLM-produced intake YAML."
        )
        intake = _prompt_character_intake(args.user_name, slug=args.slug)
        if args.save_intake:
            _write_yaml(intake, Path(args.save_intake))
        result = generate_character_template_from_data(intake, out_dir=args.out_dir, force=args.force)
        result["intake"] = args.save_intake or "interactive"
    else:
        if not args.intake:
            raise PackwrightError("init requires an intake path unless --template or --interactive is used")
        result = generate_character_template(args.intake, out_dir=args.out_dir, force=args.force)
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


def _prompt_character_intake(user_name, slug=None):
    print("Packwright character intake")
    print("Basic fallback mode: fixed questions, no LLM normalization.")
    name = _prompt_required("1. 这个人物叫什么？")
    resolved_slug = normalize_slug(slug, default="") if slug else _prompt_optional_slug(name)
    relationship = _prompt_required("2. TA 和你是什么关系？例如：工作搭档 / 秘书 / 教练 / 朋友式伙伴 / 研究员。")
    primary_work = _prompt_list("3. 你主要希望 TA 帮你做什么？可以用逗号或分号分隔多项。")
    voice = _prompt_required("4. 你希望 TA 说话像什么样？也可以说你讨厌什么口吻。")
    continuity = _prompt_relationship_continuity()
    resolved_user_name = (
        user_name
        or os.environ.get("PACKWRIGHT_USER_NAME")
        or "the user"
    )

    return {
        "version": "0.1",
        "kind": "CharacterIntake",
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
        "1b. 给 TA 一个英文/拼音 slug？用于文件名，比如 system。留空则自动生成。\n> "
    ).strip()
    if value:
        return normalize_slug(value)
    return normalize_slug(name)


def _prompt_required(prompt):
    while True:
        value = input(prompt + "\n> ").strip()
        if value:
            return value
        print("这个字段不能为空。")


def _prompt_list(prompt):
    while True:
        value = _prompt_required(prompt)
        items = [item.strip() for item in re.split(r"[,，;；\n]+", value) if item.strip()]
        if items:
            return items
        print("至少写一项。")


def _prompt_relationship_continuity():
    prompt = (
        "5. 你希望这个角色的关系连续性到什么程度？\n"
        "   A = 只做事，不维护情绪关系\n"
        "   B = 有温度，但只记重要偏好\n"
        "   C = 更像长期陪伴，会持续记住相处细节"
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
        print("请输入 A、B、C，或直接输入 task_only / warm_selective / close_continuous。")


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
    if adapter == "codex":
        return compile_to_codex_pack(resolved, references=references)
    if adapter == "claude-code":
        return compile_to_claude_code_pack(resolved, references=references)
    if adapter == "cursor":
        return compile_to_cursor_pack(resolved, references=references)
    raise PackwrightError(f"unsupported adapter: {adapter}")


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
    except json.JSONDecodeError as exc:
        raise PackwrightError(f"invalid adapter pack manifest {pack_dir / 'manifest.json'}: {exc}")
    if not isinstance(manifest, dict):
        raise PackwrightError(f"adapter pack manifest must be a mapping: {pack_dir / 'manifest.json'}")
    return manifest


def _optional_installed_artifacts():
    return EMOTION_ENGINE_CODEX_ARTIFACTS


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
