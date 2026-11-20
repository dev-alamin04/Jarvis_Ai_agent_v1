"""
jarvis/laravel/scaffold.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Laravel Code Scaffolding Tool.

Generates controllers, models, migrations, factories, requests, resources,
and routes using artisan and best practices.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import re
from pathlib import Path

from jarvis.laravel.context import get_active_laravel_project, run_artisan
from jarvis.logger import logger


def laravel_scaffold(
    component_type: str,
    name: str,
    options: str = "",
    route_definition: str | None = None,
    project_path: Path | None = None,
) -> str:
    """
    Generate Laravel components (controller, model, migration, route, request, etc.).

    Parameters
    ----------
    component_type : str
        'controller', 'model', 'migration', 'route', 'factory', 'seeder', 'request', or 'resource'.
    name : str
        The name of the component (e.g. 'OrderController', 'Product', 'create_orders_table').
    options : str
        Extra flags for artisan (e.g. '--resource', '-mfc', '--api').
    route_definition : str | None
        For routes: route code or description (e.g. 'Route::get("/orders", [OrderController::class, "index"]);').
    """
    if not project_path:
        project_name, project_path = get_active_laravel_project()
    else:
        project_name = project_path.name

    comp = component_type.lower().strip()
    clean_name = name.strip()
    logger.info(f"[Laravel Scaffold] Scaffolding {comp} '{clean_name}' in '{project_name}'")

    # ── Handle Route Generation ──────────────────────────────────────────────
    if comp in ("route", "routes"):
        routes_file = project_path / "routes" / "api.php" if "api" in (options or "").lower() else project_path / "routes" / "web.php"
        if not routes_file.exists():
            routes_file = project_path / "routes" / "web.php"

        if route_definition and route_definition.strip():
            route_code = route_definition.strip()
        else:
            # Generate route code using gpt-4o
            from jarvis.brain import _get_client
            client = _get_client()
            prompt = (
                f"You are a Laravel expert. Write a single clean Laravel 11 route definition for: '{clean_name}'.\n"
                "Return ONLY the PHP line of code (e.g. Route::get('/...', [...]);). No markdown backticks."
            )
            try:
                resp = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=80,
                )
                route_code = (resp.choices[0].message.content or "").strip()
                route_code = re.sub(r"^```(?:php)?\s*", "", route_code, flags=re.I)
                route_code = re.sub(r"\s*```$", "", route_code).strip()
            except Exception:
                route_code = f"Route::get('/{clean_name.lower()}', function () {{\n    return response()->json(['status' => 'ok']);\n}});"

        # Append to route file
        try:
            current_routes = routes_file.read_text(encoding="utf-8")
            if not current_routes.endswith("\n"):
                current_routes += "\n"
            current_routes += f"\n// Added by Jarvis\n{route_code}\n"
            routes_file.write_text(current_routes, encoding="utf-8")
            return f"Successfully added route to `{routes_file.relative_to(project_path)}`:\n```php\n{route_code}\n```"
        except Exception as exc:
            return f"Failed to append route to {routes_file}: {exc}"

    # ── Handle Artisan Make Commands ─────────────────────────────────────────
    make_map = {
        "controller": "make:controller",
        "model": "make:model",
        "migration": "make:migration",
        "factory": "make:factory",
        "seeder": "make:seeder",
        "request": "make:request",
        "resource": "make:resource",
        "event": "make:event",
        "listener": "make:listener",
        "job": "make:job",
        "middleware": "make:middleware",
        "policy": "make:policy",
        "rule": "make:rule",
    }

    artisan_cmd = make_map.get(comp)
    if not artisan_cmd:
        valid_types = ", ".join(sorted(make_map.keys())) + ", route"
        return f"Unknown component type '{component_type}'. Supported types: {valid_types}."

    full_cmd = f"{artisan_cmd} {clean_name}"
    if options and options.strip():
        full_cmd += f" {options.strip()}"

    code, out, err = run_artisan(full_cmd, project_path=project_path)
    output = out or err or "(no output)"

    if code == 0:
        return f"Scaffolded `{comp}` successfully!\n```\n{output}\n```"
    return f"Failed to scaffold `{comp}`: {err or out}"
