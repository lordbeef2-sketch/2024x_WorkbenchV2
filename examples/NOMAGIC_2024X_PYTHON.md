# No Magic 2024x Java To Python

This is a Python bridge for the local MagicDraw or Cameo 2024x OpenAPI documented at `https://jdocs.nomagic.com/2024x/`.

It is separate from the Teamwork Cloud REST examples in this repo:

- `examples/Modules/nomagic_openapi.py` talks to the local Java API through `jpype1`.
- `examples/Modules/client.py` and `examples/Modules/commands.py` talk to Teamwork Cloud `/osmc/...` over HTTP.

## Install

1. Install `jpype1` in the same Python environment.
2. Set `MAGICDRAW_HOME` or `CAMEO_HOME` to your local 2024x installation root.
3. Start MagicDraw or Cameo and open a project.

Example:

```powershell
pip install jpype1
$env:MAGICDRAW_HOME = 'C:\Program Files\No Magic\MagicDraw 2024x'
python .\19_nomagic_openapi_project_summary.py
```

The bridge scans `lib/**/*.jar` and `plugins/**/*.jar` under the install root automatically. If you want tighter control, build `MagicDrawJVMConfig` with an explicit `classpath` list.

## Main Python Entry Points

```python
from Modules import MagicDrawJVMConfig, MagicDrawOpenAPI, build_magicdraw_openapi, get_magicdraw_api

config = MagicDrawJVMConfig.from_environment()
api = get_magicdraw_api(config)
project = api.active_project()
```

Available helpers:

- `active_project()`
- `open_projects()`
- `project_summary()`
- `project_models()`
- `project_diagrams()`
- `get_element_by_id()`
- `available_factory_methods()`
- `session()`
- `create_class()`
- `create_package()`
- `create_operation()`
- `create_diagram()`
- `get_profile()`
- `get_stereotype()`
- `element_stereotypes()`
- `has_stereotype()`
- `apply_stereotype()`
- `remove_stereotype()`
- `get_stereotype_property()`
- `set_stereotype_property()`

## Java To Python Mappings

### Active project

Java:

```java
Application app = Application.getInstance();
Project project = app.getProject();
ProjectsManager projects = app.getProjectsManager();
```

Python:

```python
api = get_magicdraw_api()
project = api.active_project()
projects = api.projects_manager()
```

### Safe edit session

Java:

```java
SessionManager.getInstance().createSession(project, "Edit class A");
try {
    classA.setName("nameB");
    SessionManager.getInstance().closeSession(project);
} catch (Exception ex) {
    SessionManager.getInstance().cancelSession(project);
    throw ex;
}
```

Python:

```python
with api.session("Edit class A", project):
    class_a.setName("nameB")
```

### Create an operation under a class

Java:

```java
Operation operation = Project.getProject(classA).getElementsFactory().createOperationInstance();
ModelElementsManager.getInstance().addElement(operation, classA);
```

Python:

```python
operation = api.create_operation(class_a, "NewOperation")
```

### Create a package or class with ElementsFactory

Java:

```java
Package pkg = project.getElementsFactory().createPackageInstance();
pkg.setName("Integration");
ModelElementsManager.getInstance().addElement(pkg, parent);
```

Python:

```python
pkg = api.create_package(parent, "Integration")
new_class = api.create_class(pkg, "IntegrationService")
```

### Create a diagram

Java:

```java
Diagram diagram = ModelElementsManager.getInstance().createDiagram(type, parent, false, false);
```

Python:

```python
diagram = api.create_diagram(parent, diagram_type)
```

### Read project models and diagrams

Java:

```java
List<Package> models = project.getModels();
Collection<DiagramPresentationElement> diagrams = project.getDiagrams();
```

Python:

```python
models = api.project_models(project)
diagrams = api.project_diagrams(project)
```

### Resolve an element by ID

Java:

```java
BaseElement element = project.getElementByID(elementId);
```

Python:

```python
element = api.get_element_by_id(element_id, project)
```

### Apply a stereotype

Java:

```java
Profile profile = StereotypesHelper.getProfile(project, "SysML");
Stereotype stereotype = StereotypesHelper.getStereotype(project, "Block", profile);
StereotypesHelper.addStereotype(element, stereotype);
```

Python:

```python
api.apply_stereotype(element, "Block", profile_name="SysML")
```

### Read or update stereotype properties

Java:

```java
Object value = StereotypesHelper.getStereotypePropertyValue(element, stereotype, "documentation");
StereotypesHelper.setStereotypePropertyValue(element, stereotype, "documentation", "Updated");
```

Python:

```python
value = api.get_stereotype_property(element, "Block", "documentation", profile_name="SysML")
updated = api.set_stereotype_property(element, "Block", "documentation", "Updated", profile_name="SysML")
```

## Scope

This layer is intentionally focused on the most common 2024x OpenAPI entry points verified from JDocs:

- `Application`
- `ProjectsManager`
- `Project`
- `SessionManager`
- `ModelElementsManager`
- `ElementsFactory`
- `StereotypesHelper`

The full Javadoc surface is much larger than what belongs in a reusable project helper. For anything more specialized, use `api.jclass("...")` for direct access to the underlying Java class.

