from abc import ABC, ABCMeta
import os, sys
import copy
from collections import OrderedDict
from numbers import Number
from dmake.common import DMakeException
import dmake.common as common


class MetaSerializerMixin(ABCMeta):
    """Used to keep track of the order of the fields in order to generate a proper doc."""
    @classmethod
    def __prepare__(metacls, name, bases, **kwargs):
        return OrderedDict()

    def __new__(cls, name, bases, namespace, **kwargs):
        result = ABCMeta.__new__(cls, name, bases, dict(namespace))
        ns = []
        for b in bases:
            if isinstance(b, MetaSerializerMixin):
                ns += b.__fields_order__
        result.__fields_order__ = tuple(ns) + tuple(namespace)
        return result

class SerializerMixin(ABC, metaclass=MetaSerializerMixin):
    pass


# Custom Exceptions
class ValidationError(Exception):
    pass

class WrongType(ValidationError):
    pass

# Serializer types
class SerializerType(object):
    allowed_types = ["bool", "int", "number", "path", "file", "dir", "string", "array", "dict"]

    def __init__(self, type, deprecated=False):
        self.type = type
        self.deprecated = deprecated

    def __eq__(self, other):
        # support comparison to simple string type representation
        if isinstance(other, str):
            return self.type == other
        return (self.type == other.type and
                self.deprecated == other.deprecated)

    def __str__(self):
        str_ = self.type
        if self.deprecated:
            str_ += " (deprecated)"
        return str_

# Serializers
class FieldSerializer(object):

    def __init__(self,
            data_type,
            optional=False,
            default=None,
            allow_null=False,
            blank=False,
            child=None,
            post_validation=lambda x: x,
            child_path_only=False,        # if True, return path relative to dmake.yml file, else return path relative to repo root
            check_path=True,
            executable=False,
            no_slash_no_space=False,
            help_text="",
            example=None,
            deprecated=None,
            migration=None):
        if not isinstance(data_type, list):
            data_type = [data_type]
        for t in data_type:
            isComplex = isinstance(t, YAML2PipelineSerializer) or isinstance(t, FieldSerializer)
            assert(isComplex or t in SerializerType.allowed_types)
            if not isComplex and (t == "array" or t == "dict"):
                if child in SerializerType.allowed_types:
                    child = FieldSerializer(child, blank = True)
                else:
                    assert(isinstance(child, FieldSerializer) or isinstance(child, YAML2PipelineSerializer))

        if default is not None:
            optional = True

        self.data_type = data_type
        self.optional = optional
        self.default = default
        self.allow_null = allow_null
        self.blank = blank
        self.post_validation = post_validation
        self.child_path_only = child_path_only
        self.check_path = check_path
        self.executable = executable
        self.no_slash_no_space = no_slash_no_space
        self.help_text = help_text
        self.example = example
        self.deprecated = deprecated
        self.migration = migration

        self.child = child
        self.value = None

    def _validate_(self, file, needed_migrations, data, field_name):
        if data is None and not self.allow_null:
            if not self.optional:
                raise ValidationError("got 'Null', expected a value of type %s" % (" -OR-\n".join([str(t) for t in self.data_type])))
            else:
                validated_data = copy.deepcopy(self.default)
        else:
            if self.migration:
                needed_migrations.append(self.migration)
            if self.deprecated:
                common.logger.warning("[DEPRECATION WARNING] D001: Field '{field}' in '{file}' is deprecated: {message}".format(field=field_name, file=file, message=self.deprecated))

            ok = False
            err = []
            for t in self.data_type:
                if isinstance(t, YAML2PipelineSerializer) or isinstance(t, FieldSerializer):
                    try:
                        validated_data = t._validate_(file, needed_migrations=needed_migrations, data=data, field_name=field_name)
                        ok = True
                        break
                    except ValidationError as e:
                        err.append(str(e).replace('\n', '\n  '))
                        continue
                else:
                    try:
                        validated_data = self._validate_type_(file, needed_migrations=needed_migrations, data_type=t, data=data, field_name=field_name)
                        ok = True
                        if isinstance(t, SerializerType) and t.deprecated:
                            common.logger.warning("[DEPRECATION WARNING] D003: Field '{field}' in '{file}' uses a deprecated type: {type} (value: {value}). Use any of {recommended_types} instead.".format(
                                field=field_name, file=file, type=t.type, value=data,
                                recommended_types=[str(t) for t in self.data_type if not (isinstance(t, SerializerType) and t.deprecated)]))
                        break
                    except WrongType as e:
                        err.append(str(e))
                        continue
            if not ok:
                if len(err) == 1:
                    raise ValidationError(err[0])
                else:
                    raise ValidationError("The error is one of the followings:\n- " + ("\n- ".join(err)))
        self.value = self.post_validation(validated_data)
        return self.value

    def _value_(self):
        return self.value

    def _default_(self):
        if self.default is None:
            raise ValidationError('Not default value provided.')
        return self.default

    def _validate_type_(self, file, needed_migrations, data_type, data, field_name):
        if data_type == "bool":
            if not isinstance(data, bool):
                raise WrongType("Expecting bool")
            return data
        elif data_type == "int":
            if not isinstance(data, int):
                raise WrongType("Expecting int")
            if isinstance(data, bool):
                common.logger.warning("[DEPRECATION WARNING] D004: Field '{field}' in '{file}' should contain an int, it currently contains a bool: {value}.".format(field=field_name, file=file, value=data))
            return data
        elif data_type == "number":
            if not isinstance(data, Number) or isinstance(data, bool):
                raise WrongType("Expecting number")
            return data
        elif data_type == "string":
            if isinstance(data, int) or isinstance(data, float):
                common.logger.warning("[DEPRECATION WARNING] D002: Field '{field}' in '{file}' should contain a string, it currently contains a {type}: {value}. Add quotes arount the value.".format(field=field_name, file=file, type=type(data), value=data))
                data = str(data)
            if not isinstance(data, str):
                raise WrongType("Expecting string")
            if not self.blank and data == "":
                raise WrongType("Expecting non-blank string")
            if self.no_slash_no_space:
                for c in ['/', ' ']:
                    if data.find(c) >= 0:
                        raise ValidationError("Character '%s' not allowed" % c)
            return data
        elif data_type in ["path", "file", "dir"]:
            dmake_path = os.path.join(os.path.dirname(file), '')  # `dmake.yml` directory, relative to repo root; ending with slash, or empty string
            assert(len(dmake_path) == 0 or dmake_path[-1] == '/')
            if not isinstance(data, str):
                raise WrongType("Expecting string")
            original_data = data
            data = os.path.normpath(data)
            if data.startswith('/'):
                # then interpret data as absolute from repo root, not from `/` host root
                data = data[1:]
                if data.startswith('/'):
                    raise WrongType("Double slash not allowed: %s" % original_data)
                # full_path is relative to repo root
                full_path = data
                if self.child_path_only:
                    # then make it relative to `dmake.yml` directory
                    data = os.path.relpath(full_path, dmake_path)
            else:
                # then interpret data as relative to `dmake.yml` directory
                # full_path is relative to repo root
                full_path = os.path.join(dmake_path, data)
                if not self.child_path_only:
                    data = full_path
            # at this point `data` is:
            # - either relative to repo root (`child_path_only==False`)
            # - or relative to `dmake.yml` directory (`child_path_only==True`)
            data = os.path.normpath(data)
            if data.startswith(".."):
                # then we are outside of the allowed scope (defined by `child_path_only`)
                raise WrongType("Trying to access a parent directory is forbidden: '%s' ('%s')" % (data, original_data))
            if self.check_path:
                if data_type == "path":
                    if not (os.path.isfile(full_path) or os.path.isdir(full_path)):
                        raise WrongType("Could not find file or directory: '%s' ('%s')" % (data, original_data))
                elif data_type == "file":
                    if not os.path.isfile(full_path):
                        raise WrongType("Could not find file: '%s' ('%s')" % (data, original_data))
                    if self.executable and not os.access(full_path, os.X_OK):
                        raise WrongType("The file must be executable: '%s' ('%s')" % (data, original_data))
                elif data_type == "dir":
                    if not os.path.isdir(full_path):
                        raise WrongType("Could not find directory: '%s' ('%s')" % (data, original_data))
            return data
        elif data_type == "array":
            if not isinstance(data, list):
                raise WrongType("Expecting array")
            valid_data = []
            for d in data:
                child = copy.deepcopy(self.child)
                valid_data.append(child._validate_(file, needed_migrations=needed_migrations, data=d, field_name=field_name))
            return valid_data
        elif data_type == "dict":
            if not isinstance(data, dict):
                raise WrongType("Expecting dict")
            valid_data = {}
            for k, d in data.items():
                child = copy.deepcopy(self.child)
                try:
                    valid_data[k] = child._validate_(file, needed_migrations=needed_migrations, data=d, field_name=field_name)
                except ValidationError as e:
                    raise ValidationError("Error with field '%s': %s" % (k, str(e)))
            return valid_data
        else:
            raise DMakeException("Unkown data type: %s" % data_type)

    def _serialize_(self, *args, **kwargs):
        if isinstance(self.value, list):
            for f in self.value:
                f._serialize_(*args, **kwargs)
        else:
            raise DMakeException("Do not known how to serialize non array field")

    def get_type_name(self, obj, padding, is_plural = False):
        if isinstance(obj, FieldSerializer) and len(obj.data_type) == 1:
            return obj.get_type_name(obj.data_type[0], padding, is_plural)

        doc_string = None
        if isinstance(obj, YAML2PipelineSerializer) or isinstance(obj, FieldSerializer):
            _, _, doc_string = obj.generate_doc(padding)
            type_str = 'object'
            help_text = ('%s with the following fields:' % ('objects' if is_plural else 'an object'))
        elif obj == "dict":
            type_str, help_text, doc_string = self.get_type_name(self.child, padding, True)
            type_str = 'free style object'
            help_text = ('%s of ' % ('dictionnaries' if is_plural else 'a dictionnary')) + help_text
        elif obj == "array":
            type_str, help_text, doc_string = self.get_type_name(self.child, padding, True)
            type_str = 'array\\<%s\\>' % type_str
            help_text = ('%s of ' % ('arrays' if is_plural else 'an array')) + help_text
        elif obj == "int":
            type_str = 'int'
            help_text = 'integers' if is_plural else 'an integer'
        elif obj == "number":
            type_str = 'number'
            help_text = 'numbers' if is_plural else 'a number'
        elif obj == "path":
            type_str = 'file or directory path'
            help_text = 'file or directory paths' if is_plural else 'a file or directory path'
        elif obj == "file":
            type_str = 'file path'
            help_text = 'file paths' if is_plural else 'a file path'
        elif obj == "dir":
            type_str = 'directory path'
            help_text = 'directories' if is_plural else 'a directory'
        elif obj == "string":
            type_str = 'string'
            help_text = 'strings' if is_plural else 'a string'
        elif obj == "bool":
            type_str = 'boolean'
            help_text = 'booleans' if is_plural else 'a boolean'
        else:
            raise Exception("Unknown type: %s" % str(obj))

        return type_str, help_text, doc_string

    # Returns a tuple (infos, help_text, doc_string)
    def generate_doc(self, padding):
        # lazy import for faster cli
        import yaml

        infos = []

        help_text = self.help_text
        if len(help_text) > 0 and help_text[-1] != '.':
            help_text += '.'

        if len(self.data_type) == 1:
            type_str, ht, doc_string = self.get_type_name(self.data_type[0], padding)
        else:
            type_str = 'mixed'
            help_text += ' It can be one of the followings:'
            doc_string = []
            for t in self.data_type:
                tn, ht, ds = self.get_type_name(t, padding + 4)
                if isinstance(t, FieldSerializer) and t.help_text is not None:
                    ht += " " + t.help_text
                doc_string.append(('%s- ' % (' ' * padding)) + ht)
                if ds is not None:
                    doc_string.append(ds)
            doc_string = '\n'.join(doc_string)

        # Add the type
        infos.append(type_str)

        if self.default is not None:
            if type(self.default) in [str, int, bool]:
                default_str = str(self.default)
            else:
                # complex type: yaml dump
                # don't use common.yaml_ordered_dump because explicit_start=False doesn't work with version set somehow
                default_str = yaml.dump(self.default, default_flow_style=True).strip()
            infos.append('default = `%s`' % default_str)

        return infos, help_text, doc_string

    def generate_example(self):
        if self.example is not None:
            return self.example
        elif self.default:
            return self.default

        value = None
        for t in self.data_type:
            if isinstance(t, YAML2PipelineSerializer) or isinstance(t, FieldSerializer):
                return t.generate_example()
            elif t == "dict":
                value = {'any_key': self.child.generate_example()}
            elif t == "array":
                value = [self.child.generate_example()]
            elif value is None:
                if t == "int":
                    value = 1
                elif t in ["path", "file", "dir"]:
                    if self.child_path_only:
                        value = "some/relative/%s/example" % t
                    else:
                        value = "some/%s/example" % t
                elif t == "string":
                    value = "Some string"
                elif t == "bool":
                    value = True
                else:
                    raise DMakeException("Unknown type: %s" % str(t))
        return value

class YAML2PipelineSerializer(SerializerMixin):
    def __init__(self, optional = False, help_text = ""):
        self.__optional__  = optional
        self.__help_text__ = help_text
        self.__has_value__ = False

        if sys.version_info >= (3,0):
            fields_list = self.__fields_order__
        else:
            fields_list = dir(self)

        fields = OrderedDict()
        for k in fields_list:
            if k.startswith('_'):
                continue
            v = getattr(self, k)
            if isinstance(v, FieldSerializer) or isinstance(v, YAML2PipelineSerializer):
                fields[k] = copy.deepcopy(v)
        self.__fields__ = fields

    def _validate_(self, file, needed_migrations, data, field_name=''):
        if data is None:
            if self.__optional__:
                return None
            data = {}
        if not isinstance(data, dict):
            raise WrongType("Expecting dict, got {}".format(type(data).__name__))
        for name, serializer in self.__fields__.items():
            try:
                serializer._validate_(file,
                                      needed_migrations=needed_migrations,
                                      data=data[name] if name in data else None,
                                      field_name=field_name + ':' + name if field_name else name)
            except ValidationError as e:
                raise ValidationError("Error with field '%s': %s" % (name, str(e)))
        for key in data:
            if not isinstance(key, str):
                raise ValidationError("Expected a field name, got: '%s'" % str(key))
            if key not in self.__fields__:
                raise ValidationError("Unexpected field '%s'" % key)
        self.__has_value__ = True
        return self

    def __getattribute__(self, key):
        try:
            fields = object.__getattribute__(self, '__fields__')
        except AttributeError:
            return object.__getattribute__(self, key)
        has_data = object.__getattribute__(self, '__has_value__')
        if key in fields:
            if isinstance(fields[key], FieldSerializer):
                if has_data:
                    return fields[key]._value_()
                else:
                    raise Exception("No data has been validated yet, cannot access field '%s'" % key)
            else:
                return fields[key]
        else:
            return object.__getattribute__(self, key)

    def has_value(self):
        return self.__has_value__

    def _value_(self):
        if not self.__has_value__:
            return None
        value = {}
        for k, v in self.__fields__.items():
            value[k] = v._value_()
        return value

    def default_value(self):
        value = {}
        for k, v in self.__fields__.items():
            try:
                value[k] = v._default_()
            except ValidationError as e:
                raise DMakeException("Field '%s': %s" % (k, str(e)))
        return value

    # Returns a tuple (infos, help_text, doc_string)
    def generate_doc(self, padding = 0):
        lines = []
        for key, field in self.__fields__.items():
            infos, help_text, doc_string = field.generate_doc(padding + 4)

            infos = ', '.join(infos)
            if infos:
                infos = ' *(%s)*' % infos

            lines.append('%s- **%s**%s: %s' % (' ' * padding, key, infos, help_text))
            if doc_string is not None:
                lines.append(doc_string)

        help_text = self.__help_text__
        if len(help_text) > 0 and help_text[-1] != '.':
            help_text += '.'
        help_text += ' It must be an object with the following fields:'

        doc_string = '\n'.join(lines)

        infos = ['object']
        if self.__optional__:
            infos.append('optional')
        return infos, help_text, doc_string

    def generate_example(self):
        ex = OrderedDict()
        for key, field in self.__fields__.items():
            value = field.generate_example()
            if value == "":
                continue
            ex[key] = value
        return ex
