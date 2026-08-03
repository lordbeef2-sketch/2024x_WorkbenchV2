# Created by: Raymond Reeves Engineering Tech 4 2026
from Modules import (
    MagicDrawJVMConfig,
    get_active_project,
    get_project_summary,
    list_factory_methods,
    list_open_projects,
    list_project_models,
    print_json,
)


def main() -> None:
    config = MagicDrawJVMConfig.from_environment()
    project = get_active_project(config=config)
    payload = get_project_summary(project, config=config)
    payload["models"] = [str(model.getName()) for model in list_project_models(project, config=config)]
    payload["open_project_count"] = len(list_open_projects(config=config))
    payload["factory_method_sample"] = list_factory_methods(project, config=config)[:10]
    print_json(payload)


if __name__ == "__main__":
    main()
# Fully-commented edition notes:
# - File path: examples/19_nomagic_openapi_project_summary.py
# - This branch intentionally carries extra explanatory comments for handoff, review, and training.
# - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
# - The normal main branch keeps the production-readable version with only provenance headers.