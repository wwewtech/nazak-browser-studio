"""`nazak warmup/scenario/sync ...` — паритет WarmupView + SynchronizerDialog."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from rich.table import Table

from .common import (
    EXIT_CONFLICT,
    EXIT_NOT_FOUND,
    EXIT_OK,
    GlobalOptions,
    console,
    emit,
    emit_error,
    emit_success,
    get_managers,
    parse_ids,
    resolve_ids,
    server_request,
)

SCENARIO_ALIASES = {
    "ecommerce_trust_booster": "scen_ecom_trust",
    "youtube_shorts_warmup": "scen_youtube_viewer",
    "crypto_web3_farming": "scen_crypto_web3",
    "finance_high_cpc_banking": "scen_finance_banking",
}


def _background_scenario_command(args) -> list[str]:
    """Команда для отдельного процесса, который реально выполнит прогрев."""
    cmd = [sys.executable, "-m", "nazak.cli", "scenario", "run", "--wait", "--profiles", ",".join(args.profiles or [])]
    if getattr(args, "all", False):
        cmd.append("--all")
    if getattr(args, "scenario", None):
        cmd += ["--scenario", args.scenario]
    if getattr(args, "scenario_file", None):
        cmd += ["--scenario-file", args.scenario_file]
    concurrency = getattr(args, "concurrency", None)
    if concurrency:
        cmd += ["--concurrency", str(concurrency)]
    return cmd


def _spawn_background_scenario(args, profile_ids: list[str]) -> tuple[int, Path] | None:
    """Запускает прогрев отдельным процессом; возвращает (pid, путь к логу).

    Audit R3-round2: фон обязан переживать выход CLI, иначе «success» — ложь.
    """
    import subprocess

    from ..config import LOGS_DIR

    args.profiles = profile_ids
    cmd = _background_scenario_command(args)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"scenario_{time.strftime('%Y%m%d_%H%M%S')}.log"
    creationflags = 0
    popen_kwargs: dict = {}
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: процесс не привязан к
        # консоли CLI и не получает Ctrl+C вместе с ней.
        creationflags = 0x00000008 | 0x00000200
    else:
        popen_kwargs["start_new_session"] = True
    try:
        log_file = log_path.open("ab")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                **popen_kwargs,
            )
        finally:
            log_file.close()
    except Exception as exc:
        console.print(f"[red]Фоновый запуск не удался: {exc}[/red]")
        return None
    return proc.pid, log_path


def register(sp) -> None:
    w = sp.add_parser("warmup", help="Warmup: план и запуск прогрев-URL")
    wsub = w.add_subparsers(dest="warmup_action", required=True)
    s = wsub.add_parser("plan", help="Сгенерировать план прогрева (без запуска)")
    s.add_argument("profile_id")
    s.add_argument("--niche", default="ecommerce", choices=["ecommerce", "finance", "tech", "travel", "crypto"])
    s.add_argument("--steps", type=int, default=5)
    s.set_defaults(func=cmd_warmup_plan)
    s = wsub.add_parser("launch", help="Запустить браузер на warmup-стартовом URL")
    s.add_argument("profile_id")
    s.add_argument("--niche", default="ecommerce", choices=["ecommerce", "finance", "tech", "travel", "crypto"])
    s.add_argument("--steps", type=int, default=5)
    s.set_defaults(func=cmd_warmup_launch)

    sc = sp.add_parser("scenario", help="Сценарии автономного прогрева (E-com/YouTube/Crypto/Finance)")
    scsub = sc.add_subparsers(dest="scenario_action", required=True)
    s = scsub.add_parser("list", help="Список built-in сценариев")
    s.set_defaults(func=cmd_scenario_list)
    s = scsub.add_parser("run", help="Запустить сценарий по пулу профилей")
    s.add_argument("--scenario", default=None, help="ID сценария или алиас (см. scenario list)")
    s.add_argument("--scenario-file", default=None, help="JSON WarmupScenario.from_dict")
    s.add_argument("--profiles", default="", help="CSV профилей")
    s.add_argument("--all", action="store_true")
    s.add_argument("--concurrency", type=int, default=3)
    s.add_argument("--wait", action="store_true", help="Дождаться завершения (иначе фон)")
    s.set_defaults(func=cmd_scenario_run)

    sy = sp.add_parser("sync", help="Синхронизатор Master→Workers + Win32-сетка")
    sysub = sy.add_subparsers(dest="sync_action", required=True)
    s = sysub.add_parser("start", help="Старт сессии синхронизации")
    s.add_argument("--master", required=True, help="ID master-профиля")
    s.add_argument("--workers", required=True, help="CSV worker-профилей")
    s.add_argument("--no-jitter", action="store_true", help="Отключить humanizer")
    s.add_argument("--min-delay", type=int, default=20)
    s.add_argument("--max-delay", type=int, default=80)
    s.add_argument("--coord-jitter", type=int, default=2)
    s.set_defaults(func=cmd_sync_start)
    s = sysub.add_parser("stop", help="Стоп сессии")
    s.set_defaults(func=cmd_sync_stop)
    s = sysub.add_parser("status", help="Статус сессии")
    s.set_defaults(func=cmd_sync_status)
    s = sysub.add_parser("tile", help="Разложить окна в сетку (Win32)")
    s.add_argument("--cols", type=int, default=None)
    s.set_defaults(func=cmd_sync_tile)
    s = sysub.add_parser("navigate", help="Разослать URL всем workers")
    s.add_argument("url", help="https://...")
    s.set_defaults(func=cmd_sync_navigate)


def _via_server(opt: GlobalOptions, method: str, path: str, **kw):
    emit(server_request(opt, method, path, **kw), opt)
    return EXIT_OK


def cmd_warmup_plan(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(
            opt,
            "POST",
            f"/api/profiles/{args.profile_id}/warmup/plan",
            json={"niche": args.niche, "steps_count": args.steps},
        )
    from nazak.core.warmup_engine import WarmupPlan

    pm, _ = get_managers()
    if not pm.get_profile(args.profile_id):
        return emit_error("Профиль не найден", opt, EXIT_NOT_FOUND)
    plan = WarmupPlan(profile_id=args.profile_id, niche=args.niche, steps_count=args.steps)
    emit({"success": True, "plan": plan.to_dict()}, opt)
    return EXIT_OK


def cmd_warmup_launch(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(
            opt,
            "POST",
            f"/api/profiles/{args.profile_id}/warmup/launch",
            json={"niche": args.niche, "steps_count": args.steps},
        )
    from nazak.core.warmup_engine import WarmupPlan
    from nazak.models.profile import ProfileStatus

    pm, bl = get_managers()
    p = pm.get_profile(args.profile_id)
    if not p:
        return emit_error("Профиль не найден", opt, EXIT_NOT_FOUND)
    plan = WarmupPlan(profile_id=args.profile_id, niche=args.niche, steps_count=args.steps)
    from nazak.core.warmup_engine import generate_warmup_urls as _gen

    urls = _gen(plan.queries)
    start_url = urls[0] if urls else "https://www.google.com"
    ok, pid, err = bl.launch(p, custom_url=start_url)
    if not ok:
        return emit_error(err or "Launch failed", opt, EXIT_CONFLICT)
    p.status, p.pid = ProfileStatus.RUNNING, pid
    pm.update_profile(p)
    return emit_success(f"Warmup запущен pid={pid}", opt, {"pid": pid, "start_url": start_url, "plan": plan.to_dict()})


def cmd_scenario_list(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", "/api/scenarios")
    from nazak.core.warmup_engine import BUILTIN_SCENARIOS

    items = [s.to_dict() for s in BUILTIN_SCENARIOS]
    if opt.as_json:
        emit({"success": True, "scenarios": items, "aliases": SCENARIO_ALIASES}, opt)
    else:
        t = Table(title="Warmup scenarios")
        t.add_column("ID")
        t.add_column("Name")
        t.add_column("Steps")
        for s in BUILTIN_SCENARIOS:
            d = s.to_dict()
            steps = d.get("steps", [])
            t.add_row(s.id, s.name, str(len(steps)))
        console.print(t)
        console.print(f"[dim]Алиасы: {SCENARIO_ALIASES}[/dim]")
    return EXIT_OK


def _find_scenario(scenario_id: str | None, scenario_file: str | None):
    from nazak.core.warmup_engine import BUILTIN_SCENARIOS, WarmupScenario

    if scenario_file:
        data = json.loads(Path(scenario_file).read_text(encoding="utf-8"))
        return WarmupScenario.from_dict(data), None
    if not scenario_id:
        return None, "Укажите --scenario или --scenario-file"
    target = SCENARIO_ALIASES.get(scenario_id, scenario_id)
    for s in BUILTIN_SCENARIOS:
        if s.id == target:
            return s, None
    valid = [s.id for s in BUILTIN_SCENARIOS] + list(SCENARIO_ALIASES)
    return None, f"Неизвестный scenario '{scenario_id}'. Доступны: {valid}"


def cmd_scenario_run(args, opt: GlobalOptions) -> int:
    ids = resolve_ids(parse_ids(args.profiles), allow_all=args.all)
    if not ids:
        return emit_error("Укажите --profiles id1,id2 или --all", opt)
    if opt.server:
        body: dict = {"profile_ids": ids, "max_concurrency": args.concurrency}
        if args.scenario_file:
            body["scenario_data"] = json.loads(Path(args.scenario_file).read_text(encoding="utf-8"))
        else:
            body["scenario_id"] = args.scenario
        return _via_server(opt, "POST", "/api/scenarios/run", json=body)
    from nazak.core.warmup_engine import ScenarioExecutor

    scenario, err = _find_scenario(args.scenario, args.scenario_file)
    if err:
        return emit_error(err, opt)
    pm, bl = get_managers()
    missing = [pid for pid in ids if not pm.get_profile(pid)]
    if missing:
        return emit_error(f"Профили не найдены: {missing}", opt, EXIT_NOT_FOUND)
    ex = ScenarioExecutor(bl, pm)
    if args.wait:
        res = asyncio.run(ex.run_batch_warmup(scenario=scenario, profile_ids=ids, max_concurrency=args.concurrency))
        emit({"success": True, "results": res}, opt)
    else:
        # Audit R3-round2: раньше здесь стартовал daemon-поток и команда сразу
        # печатала success. main.py делает `raise SystemExit(run_cli())`, поэтому
        # daemon-поток умирал на выходе интерпретатора: работа не выполнялась
        # ВООБЩЕ, а агент получал success + exit 0. Теперь фон — это отдельный
        # процесс (переживает выход CLI), с логом и pid в ответе.
        launched = _spawn_background_scenario(args, ids)
        if launched is None:
            return emit_error(
                "Не удалось запустить сценарий в фоне. Запустите с --wait для синхронного выполнения.",
                opt,
                EXIT_CONFLICT,
            )
        pid, log_path = launched
        return emit_success(
            f"Сценарий '{scenario.name}' запущен фоном для {len(ids)} профилей (pid={pid}, лог: {log_path})",
            opt,
            {"scenario": scenario.id, "profiles": ids, "pid": pid, "log": str(log_path), "background": True},
        )
    return EXIT_OK


# Synchronizer — direct через singleton; в server-режиме через API.

_sync_mgr = None


def _get_sync_mgr():
    global _sync_mgr
    if _sync_mgr is None:
        from nazak.core.synchronizer import SynchronizerManager

        _, bl = get_managers()
        _sync_mgr = SynchronizerManager(bl)
        try:
            bl.set_event_sink(_sync_mgr.submit_event)
        except Exception:
            pass
    return _sync_mgr


def cmd_sync_start(args, opt: GlobalOptions) -> int:
    workers = parse_ids(args.workers)
    if not workers:
        return emit_error("Укажите --workers id1,id2", opt)
    if opt.server:
        return _via_server(
            opt,
            "POST",
            "/api/synchronizer/start",
            json={
                "master_profile_id": args.master,
                "worker_profile_ids": workers,
                "humanize_jitter": not args.no_jitter,
                "min_delay_ms": args.min_delay,
                "max_delay_ms": args.max_delay,
                "coordinate_jitter_px": args.coord_jitter,
            },
        )
    pm, _ = get_managers()
    if not pm.get_profile(args.master):
        return emit_error("Master не найден", opt, EXIT_NOT_FOUND)
    missing = [w for w in workers if not pm.get_profile(w)]
    if missing:
        return emit_error(f"Workers не найдены: {missing}", opt, EXIT_NOT_FOUND)
    mgr = _get_sync_mgr()
    sess = mgr.start_session(
        master_profile_id=args.master,
        worker_profile_ids=workers,
        humanize_jitter=not args.no_jitter,
        delay_range_ms=(args.min_delay, args.max_delay),
        coordinate_jitter_px=args.coord_jitter,
    )
    return emit_success("Синхронизация запущена", opt, {"session": sess.to_dict()})


def cmd_sync_stop(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "POST", "/api/synchronizer/stop")
    _get_sync_mgr().stop_session()
    return emit_success("Синхронизация остановлена", opt)


def cmd_sync_status(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "GET", "/api/synchronizer/status")
    emit({"success": True, "status": _get_sync_mgr().get_status()}, opt)
    return EXIT_OK


def cmd_sync_tile(args, opt: GlobalOptions) -> int:
    if opt.server:
        body = {"cols": args.cols} if args.cols else {}
        return _via_server(opt, "POST", "/api/synchronizer/tile-windows", json=body)
    ok = _get_sync_mgr().tile_active_windows(cols=args.cols)
    if not ok:
        return emit_error("Не удалось разложить окна (только Windows + запущенные браузеры)", opt, EXIT_CONFLICT)
    return emit_success("Окна разложены в сетку", opt)


def cmd_sync_navigate(args, opt: GlobalOptions) -> int:
    if opt.server:
        return _via_server(opt, "POST", "/api/synchronizer/navigate", json={"url": args.url})
    results = asyncio.run(_get_sync_mgr().mirror_navigation(args.url))
    emit({"success": True, "results": results}, opt)
    return EXIT_OK
