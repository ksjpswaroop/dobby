```markdown
# dobby Development Patterns

> Auto-generated skill from repository analysis

## Overview
This skill teaches you the core development patterns and conventions used in the `dobby` Python codebase. You'll learn how to structure files, write imports and exports, follow commit message conventions, and organize and run tests. The repository uses Python without a specific framework, and emphasizes clarity and consistency in code organization.

## Coding Conventions

### File Naming
- Use **snake_case** for all file names.
  - Example: `my_module.py`, `data_processor.py`

### Import Style
- Prefer **relative imports** within the codebase.
  - Example:
    ```python
    from .utils import helper_function
    ```

### Export Style
- Mixed: both explicit and implicit exports are used.
  - Example (explicit):
    ```python
    __all__ = ['MyClass', 'my_function']
    ```
  - Example (implicit):
    ```python
    class MyClass:
        ...
    ```

### Commit Messages
- Use **conventional commits** with the `feat` prefix for new features.
  - Example:
    ```
    feat: add user authentication to login module
    ```

## Workflows

### Creating a New Feature
**Trigger:** When adding new functionality to the codebase  
**Command:** `/create-feature`

1. Create a new Python file using snake_case naming.
2. Implement the feature using relative imports as needed.
3. Write or update tests in a corresponding `*.test.*` file.
4. Commit your changes with a conventional commit message:
    ```
    feat: short description of the feature
    ```
5. Push your branch and open a pull request.

### Writing and Running Tests
**Trigger:** When verifying code correctness or adding new features  
**Command:** `/run-tests`

1. Write tests in files matching the pattern `*.test.*` (e.g., `user.test.py`).
2. Use the available (unknown) test framework to run tests.
3. Ensure all tests pass before merging changes.

## Testing Patterns

- Test files are named with the pattern `*.test.*` (e.g., `module.test.py`).
- The specific test framework is not detected; inspect existing test files for style.
- Place tests alongside the code or in a dedicated `tests/` directory as appropriate.

**Example test file:**
```python
# user.test.py

def test_user_creation():
    user = User('alice')
    assert user.name == 'alice'
```

## Commands
| Command         | Purpose                                      |
|-----------------|----------------------------------------------|
| /create-feature | Start a new feature with proper conventions  |
| /run-tests      | Run all test files in the codebase           |
```
