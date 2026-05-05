from __future__ import annotations

import importlib
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence


ENV_HOME_NAMES = ("MAGICDRAW_HOME", "CAMEO_HOME", "NOMAGIC_HOME")
DEFAULT_JAR_GLOBS = ("lib/**/*.jar", "plugins/**/*.jar")


class NoMagicOpenApiError(RuntimeError):
    """Raised when the local MagicDraw or Cameo Java bridge cannot continue."""


def _dedupe_paths(paths: Sequence[str | Path]) -> list[str]:
    resolved: list[str] = []
    seen: set[str] = set()
    for raw_path in paths:
        text = str(raw_path).strip()
        if not text:
            continue
        normalized = str(Path(text).expanduser())
        key = normalized.lower() if os.name == "nt" else normalized
        if key in seen:
            continue
        seen.add(key)
        resolved.append(normalized)
    return resolved


def _collection_to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (str, bytes, int, float, bool)):
        return [value]
    try:
        return list(value)
    except TypeError:
        size_method = getattr(value, "size", None)
        get_method = getattr(value, "get", None)
        if callable(size_method) and callable(get_method):
            return [get_method(index) for index in range(size_method())]
        return [value]


def _to_python_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bytes, int, float, bool)):
        return value
    if isinstance(value, tuple):
        return [_to_python_value(item) for item in value]
    if isinstance(value, list):
        return [_to_python_value(item) for item in value]
    if hasattr(value, "iterator") or hasattr(value, "size"):
        return [_to_python_value(item) for item in _collection_to_list(value)]
    return value


@dataclass(slots=True)
class MagicDrawJVMConfig:
    installation_dir: str | Path | None = None
    classpath: list[str | Path] = field(default_factory=list)
    jar_globs: tuple[str, ...] = DEFAULT_JAR_GLOBS
    jvm_path: str | Path | None = None
    jvm_args: list[str] = field(default_factory=list)
    convert_strings: bool = True

    @classmethod
    def from_environment(cls) -> "MagicDrawJVMConfig":
        home = next((os.getenv(name) for name in ENV_HOME_NAMES if os.getenv(name)), None)
        return cls(installation_dir=home or None)

    def resolved_installation_dir(self) -> Path | None:
        if self.installation_dir is None:
            return None
        return Path(self.installation_dir).expanduser()

    def resolved_classpath(self) -> list[str]:
        candidates: list[str | Path] = []
        install_dir = self.resolved_installation_dir()
        if install_dir and install_dir.exists():
            for jar_glob in self.jar_globs:
                candidates.extend(sorted(install_dir.glob(jar_glob)))
        candidates.extend(self.classpath)
        return _dedupe_paths(candidates)


class MagicDrawOpenAPI:
    def __init__(self, config: MagicDrawJVMConfig | None = None) -> None:
        self.config = config or MagicDrawJVMConfig.from_environment()
        self._jpype: Any | None = None
        self._classes: dict[str, Any] = {}

    def _load_jpype(self) -> Any:
        if self._jpype is not None:
            return self._jpype
        try:
            jpype = importlib.import_module("jpype")
            importlib.import_module("jpype.imports")
        except ModuleNotFoundError as exc:
            raise NoMagicOpenApiError(
                "jpype1 is required for the No Magic Java bridge. Install it with 'pip install jpype1'."
            ) from exc
        self._jpype = jpype
        return jpype

    def start(self) -> None:
        jpype = self._load_jpype()
        if jpype.isJVMStarted():
            return

        classpath = self.config.resolved_classpath()
        if not classpath:
            raise NoMagicOpenApiError(
                "No Magic classpath could not be resolved. Set MAGICDRAW_HOME, CAMEO_HOME, or pass explicit jar paths."
            )

        startup_args: list[str] = []
        if self.config.jvm_path:
            startup_args.append(str(Path(self.config.jvm_path).expanduser()))
        startup_args.extend(self.config.jvm_args)
        jpype.startJVM(*startup_args, classpath=classpath, convertStrings=self.config.convert_strings)

    def jclass(self, class_name: str) -> Any:
        self.start()
        if class_name not in self._classes:
            self._classes[class_name] = self._load_jpype().JClass(class_name)
        return self._classes[class_name]

    def application(self) -> Any:
        return self.jclass("com.nomagic.magicdraw.core.Application").getInstance()

    def projects_manager(self) -> Any:
        return self.application().getProjectsManager()

    def active_project(self) -> Any:
        project = self.application().getProject()
        if project is None:
            project = self.projects_manager().getActiveProject()
        if project is None:
            raise NoMagicOpenApiError("No active MagicDraw or Cameo project is open.")
        return project

    def open_projects(self) -> list[Any]:
        return _collection_to_list(self.projects_manager().getProjects())

    def require_project(self, project: Any | None = None) -> Any:
        return project if project is not None else self.active_project()

    def project_for_element(self, element: Any) -> Any:
        if element is None:
            raise NoMagicOpenApiError("An element instance is required.")
        project = self.jclass("com.nomagic.magicdraw.core.Project").getProject(element)
        if project is None:
            raise NoMagicOpenApiError("Unable to resolve a project for the supplied element.")
        return project

    def project_summary(self, project: Any | None = None) -> dict[str, Any]:
        resolved_project = self.require_project(project)
        return {
            "name": str(resolved_project.getName()),
            "file_name": resolved_project.getFileName(),
            "is_remote": bool(resolved_project.isRemote()),
            "is_esi_project": bool(resolved_project.isEsiProject()),
            "model_count": len(self.project_models(resolved_project)),
            "diagram_count": len(self.project_diagrams(resolved_project)),
        }

    def project_models(self, project: Any | None = None) -> list[Any]:
        return _collection_to_list(self.require_project(project).getModels())

    def project_diagrams(self, project: Any | None = None, diagram_type: str | None = None) -> list[Any]:
        resolved_project = self.require_project(project)
        diagrams = resolved_project.getDiagrams(diagram_type) if diagram_type else resolved_project.getDiagrams()
        return _collection_to_list(diagrams)

    def get_element_by_id(self, element_id: str, project: Any | None = None) -> Any:
        if not element_id.strip():
            raise NoMagicOpenApiError("element_id is required.")
        return self.require_project(project).getElementByID(element_id)

    def elements_factory(self, project: Any | None = None) -> Any:
        return self.require_project(project).getElementsFactory()

    def available_factory_methods(self, project: Any | None = None) -> list[str]:
        factory = self.elements_factory(project)
        return sorted(name for name in dir(factory) if name.startswith("create") and name.endswith("Instance"))

    def session_manager(self) -> Any:
        return self.jclass("com.nomagic.magicdraw.openapi.uml.SessionManager").getInstance()

    def model_elements_manager(self) -> Any:
        return self.jclass("com.nomagic.magicdraw.openapi.uml.ModelElementsManager").getInstance()

    def stereotypes_helper(self) -> Any:
        return self.jclass("com.nomagic.uml2.ext.jmi.helpers.StereotypesHelper")

    @contextmanager
    def session(self, session_name: str, project: Any | None = None) -> Iterator[Any]:
        if not session_name.strip():
            raise NoMagicOpenApiError("session_name is required.")
        resolved_project = self.require_project(project)
        manager = self.session_manager()
        created_here = not bool(manager.isSessionCreated(resolved_project))
        if created_here:
            manager.createSession(resolved_project, session_name)
        try:
            yield resolved_project
        except Exception:
            if created_here and manager.isSessionCreated(resolved_project):
                manager.cancelSession(resolved_project)
            raise
        else:
            if created_here and manager.isSessionCreated(resolved_project):
                manager.closeSession(resolved_project)

    def create_element(
        self,
        factory_method: str,
        parent: Any,
        *,
        name: str | None = None,
        project: Any | None = None,
        session_name: str | None = None,
    ) -> Any:
        if parent is None:
            raise NoMagicOpenApiError("parent is required.")
        resolved_project = self.require_project(project or self.project_for_element(parent))
        factory = self.elements_factory(resolved_project)
        creator = getattr(factory, factory_method, None)
        if not callable(creator):
            raise NoMagicOpenApiError(f"ElementsFactory does not expose {factory_method}().")

        resolved_session_name = session_name or f"Create via {factory_method}"
        with self.session(resolved_session_name, resolved_project):
            element = creator()
            if name is not None:
                set_name = getattr(element, "setName", None)
                if not callable(set_name):
                    raise NoMagicOpenApiError(f"Result of {factory_method}() does not expose setName().")
                set_name(name)
            self.model_elements_manager().addElement(element, parent)
            return element

    def create_class(self, parent: Any, name: str, *, project: Any | None = None, session_name: str | None = None) -> Any:
        return self.create_element(
            "createClassInstance",
            parent,
            name=name,
            project=project,
            session_name=session_name or f"Create class {name}",
        )

    def create_package(self, parent: Any, name: str, *, project: Any | None = None, session_name: str | None = None) -> Any:
        return self.create_element(
            "createPackageInstance",
            parent,
            name=name,
            project=project,
            session_name=session_name or f"Create package {name}",
        )

    def create_operation(self, parent: Any, name: str, *, project: Any | None = None, session_name: str | None = None) -> Any:
        return self.create_element(
            "createOperationInstance",
            parent,
            name=name,
            project=project,
            session_name=session_name or f"Create operation {name}",
        )

    def create_diagram(
        self,
        parent: Any,
        diagram_type: str,
        *,
        open_diagram: bool = False,
        open_in_active_tab: bool = False,
        project: Any | None = None,
        session_name: str | None = None,
    ) -> Any:
        if parent is None:
            raise NoMagicOpenApiError("parent is required.")
        if not diagram_type.strip():
            raise NoMagicOpenApiError("diagram_type is required.")
        resolved_project = self.require_project(project or self.project_for_element(parent))
        resolved_session_name = session_name or f"Create {diagram_type} diagram"
        with self.session(resolved_session_name, resolved_project):
            return self.model_elements_manager().createDiagram(
                diagram_type,
                parent,
                bool(open_diagram),
                bool(open_in_active_tab),
            )

    def get_profile(self, profile_name: str, project: Any | None = None) -> Any:
        if not profile_name.strip():
            raise NoMagicOpenApiError("profile_name is required.")
        return self.stereotypes_helper().getProfile(self.require_project(project), profile_name)

    def get_stereotype(
        self,
        stereotype_name: str,
        *,
        profile_name: str | None = None,
        project: Any | None = None,
    ) -> Any:
        if not stereotype_name.strip():
            raise NoMagicOpenApiError("stereotype_name is required.")
        resolved_project = self.require_project(project)
        profile = self.get_profile(profile_name, resolved_project) if profile_name else None
        return self.stereotypes_helper().getStereotype(resolved_project, stereotype_name, profile)

    def element_stereotypes(self, element: Any) -> list[Any]:
        if element is None:
            raise NoMagicOpenApiError("element is required.")
        return _collection_to_list(self.stereotypes_helper().getStereotypes(element))

    def has_stereotype(
        self,
        element: Any,
        stereotype_name: str,
        *,
        profile_name: str | None = None,
        project: Any | None = None,
    ) -> bool:
        stereotype = self.get_stereotype(stereotype_name, profile_name=profile_name, project=project)
        if stereotype is None:
            return False
        return bool(self.stereotypes_helper().hasStereotype(element, stereotype))

    def apply_stereotype(
        self,
        element: Any,
        stereotype_name: str,
        *,
        profile_name: str | None = None,
        project: Any | None = None,
        session_name: str | None = None,
    ) -> Any:
        if element is None:
            raise NoMagicOpenApiError("element is required.")
        resolved_project = self.require_project(project or self.project_for_element(element))
        stereotype = self.get_stereotype(stereotype_name, profile_name=profile_name, project=resolved_project)
        if stereotype is None:
            raise NoMagicOpenApiError(f"Stereotype '{stereotype_name}' was not found.")
        helper = self.stereotypes_helper()
        if helper.hasStereotype(element, stereotype):
            return stereotype
        if not helper.canApplyStereotype(element, stereotype):
            raise NoMagicOpenApiError(f"Stereotype '{stereotype_name}' cannot be applied to the target element.")
        with self.session(session_name or f"Apply stereotype {stereotype_name}", resolved_project):
            helper.addStereotype(element, stereotype)
        return stereotype

    def remove_stereotype(
        self,
        element: Any,
        stereotype_name: str,
        *,
        profile_name: str | None = None,
        project: Any | None = None,
        session_name: str | None = None,
    ) -> bool:
        if element is None:
            raise NoMagicOpenApiError("element is required.")
        resolved_project = self.require_project(project or self.project_for_element(element))
        stereotype = self.get_stereotype(stereotype_name, profile_name=profile_name, project=resolved_project)
        if stereotype is None or not self.stereotypes_helper().hasStereotype(element, stereotype):
            return False
        with self.session(session_name or f"Remove stereotype {stereotype_name}", resolved_project):
            self.stereotypes_helper().removeStereotype(element, stereotype)
        return True

    def get_stereotype_property(
        self,
        element: Any,
        stereotype_name: str,
        property_name: str,
        *,
        profile_name: str | None = None,
        project: Any | None = None,
    ) -> Any:
        if element is None:
            raise NoMagicOpenApiError("element is required.")
        if not property_name.strip():
            raise NoMagicOpenApiError("property_name is required.")
        resolved_project = self.require_project(project or self.project_for_element(element))
        stereotype = self.get_stereotype(stereotype_name, profile_name=profile_name, project=resolved_project)
        if stereotype is None:
            raise NoMagicOpenApiError(f"Stereotype '{stereotype_name}' was not found.")
        value = self.stereotypes_helper().getStereotypePropertyValue(element, stereotype, property_name)
        return _to_python_value(value)

    def set_stereotype_property(
        self,
        element: Any,
        stereotype_name: str,
        property_name: str,
        value: Any,
        *,
        profile_name: str | None = None,
        project: Any | None = None,
        session_name: str | None = None,
    ) -> Any:
        if element is None:
            raise NoMagicOpenApiError("element is required.")
        if not property_name.strip():
            raise NoMagicOpenApiError("property_name is required.")
        resolved_project = self.require_project(project or self.project_for_element(element))
        stereotype = self.get_stereotype(stereotype_name, profile_name=profile_name, project=resolved_project)
        if stereotype is None:
            raise NoMagicOpenApiError(f"Stereotype '{stereotype_name}' was not found.")
        with self.session(session_name or f"Set stereotype property {property_name}", resolved_project):
            self.stereotypes_helper().setStereotypePropertyValue(element, stereotype, property_name, value)
        return self.get_stereotype_property(
            element,
            stereotype_name,
            property_name,
            profile_name=profile_name,
            project=resolved_project,
        )


_DEFAULT_API: MagicDrawOpenAPI | None = None


def build_magicdraw_openapi(config: MagicDrawJVMConfig | None = None) -> MagicDrawOpenAPI:
    api = MagicDrawOpenAPI(config)
    api.start()
    return api


def get_magicdraw_api(config: MagicDrawJVMConfig | None = None) -> MagicDrawOpenAPI:
    global _DEFAULT_API
    if config is not None:
        _DEFAULT_API = MagicDrawOpenAPI(config)
        return _DEFAULT_API
    if _DEFAULT_API is None:
        _DEFAULT_API = MagicDrawOpenAPI()
    return _DEFAULT_API


__all__ = [
    "MagicDrawJVMConfig",
    "MagicDrawOpenAPI",
    "NoMagicOpenApiError",
    "build_magicdraw_openapi",
    "get_magicdraw_api",
]
