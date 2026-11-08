"""Schema of the Victoria 2 scripting language and the file validator.

The schema itself is data (YAML in ``vic2toolmod/schema/data``), described in
``docs/schema.md``. `load_schema` reads it, `Validator` checks parsed files.
"""

from vic2toolmod.schema.loader import SchemaError, default_schema, load_schema
from vic2toolmod.schema.validator import Validator, file_type_for

__all__ = ["SchemaError", "Validator", "default_schema", "file_type_for", "load_schema"]
