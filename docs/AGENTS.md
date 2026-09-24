# Project Guidelines

## Project

This is a Django application written in Python.

The project analyzes traffic accident datasets and generates
traffic engineering analyses.

## Architecture

Prefer simple and modular solutions.

Follow these principles:

- separation of responsibilities
- low coupling
- high cohesion
- SOLID when appropriate
- avoid unnecessary abstractions
- avoid duplicated code

Django views should remain thin.

Business logic should preferably live in services or domain modules
instead of views.

Data processing logic should remain separated from HTTP logic.

## Python

Use readable and explicit Python.

Prefer:

- descriptive variable names
- small functions
- type hints when useful
- pathlib instead of manual path manipulation

Avoid:

- overly clever code
- unnecessary metaprogramming
- deeply nested conditions
- huge functions

## Django

Follow Django conventions.

Before creating custom infrastructure, verify whether Django already
provides the required functionality.

Keep:

- models responsible for persistence/domain representation
- views responsible for HTTP orchestration
- services responsible for business logic
- templates responsible for presentation

## Database

Do not modify models or create migrations unless the task requires it.

Always explain database schema changes before implementing them.

## Tests

When modifying important business logic:

1. identify existing tests;
2. update or create tests when appropriate;
3. run relevant tests.

Useful commands:

python manage.py check

python manage.py test

## Safety

Do not:

- delete user data;
- run destructive database commands;
- delete migrations;
- modify secrets;
- commit .env files;
- modify production configuration without explicit instruction.

## Working style

Before making significant changes:

1. inspect the relevant files;
2. explain the current behavior;
3. propose the smallest reasonable change;
4. implement it;
5. show which files changed;
6. run appropriate validation.

Prefer incremental changes instead of large refactors.

## Learning

The owner of this project is studying Python and Django.

When implementing something non-trivial, explain:

- why the change is necessary;
- what Python/Django concept is involved;
- how the solution works.

Do not replace a simple solution with a complex abstraction only because
it is theoretically more scalable.