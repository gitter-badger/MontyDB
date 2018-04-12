import os
import importlib
from collections import MutableMapping, OrderedDict

from .storage import SQLITE_CONFIG
from .vendor import yaml
from .vendor.yaml import SafeLoader, SafeDumper
try:
    from .vendor.yaml import CLoader as Loader, CDumper as Dumper
except ImportError:
    from .vendor.yaml import Loader, Dumper


class AttribDict(MutableMapping):
    """
    Based on source:
    Thanks @nivk
    https://stackoverflow.com/a/47081357/4145300
    """

    def __init__(self, ordered):
        super(AttribDict, self).__setattr__('cnf', OrderedDict(ordered))
        super(AttribDict, self).__setattr__('__lok__', False)

    def __getattr__(self, key):
        return self.__getitem__(key)

    def __setattr__(self, key, val):
        self.__setitem__(key, val)

    def __delitem__(self, key):
        raise IOError("Can not delete option.")

    def __getitem__(self, key):
        if key not in self.cnf:
            raise IOError("Option {!r} does not exists.".format(key))
        return self.cnf[key]

    def __setitem__(self, key, val):
        if self.__lok__:
            raise IOError("Locked, all values are not changeable now.")
        if key not in self.cnf:
            raise IOError("Adding new option is not allowed.")
        if self.cnf[key] is not None and (
            not isinstance(val, type(self.cnf[key])) and
            val is not None
        ):
            raise ValueError(
                "Option value type is not changeable, except NoneType.")

        self.cnf[key] = val

    def __iter__(self):
        return iter(self.cnf)

    def __len__(self):
        return len(self.cnf)

    def __restriction__(self, *args, **kwargs):
        raise TypeError('Can not use this method.')

    clear = __restriction__
    pop = __restriction__
    popitem = __restriction__
    setdefault = __restriction__
    update = __restriction__

    def lock(self):
        super(AttribDict, self).__setattr__('__lok__', True)
        for key in self.cnf:
            if isinstance(self.cnf[key], AttribDict):
                self.cnf[key].lock()


def yaml_config_load(stream, Loader=Loader, object_pairs_hook=AttribDict):
    """
    Based on source:
    Thanks @coldfix
    https://stackoverflow.com/a/21912744/4145300
    """
    class AttribLoader(Loader):
        pass

    def construct_mapping(loader, node):
        loader.flatten_mapping(node)
        return object_pairs_hook(loader.construct_pairs(node))

    AttribLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping)

    return yaml.load(stream, AttribLoader)


def yaml_config_dump(data, stream=None, Dumper=Dumper, **kwds):
    """
    Based on source:
    Thanks @coldfix.
    https://stackoverflow.com/a/21912744/4145300
    """
    class AttribDumper(Dumper):
        pass

    def _dict_representer(dumper, data):
        return dumper.represent_mapping(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
            data.items())

    AttribDumper.add_representer(AttribDict, _dict_representer)

    return yaml.dump(data, stream, AttribDumper, **kwds)


DEFAULT_CONFIG = SQLITE_CONFIG


class MontyConfigure(object):
    """
    """

    CONFIG_FNAME = "conf.yaml"

    def __init__(self, repository=None, default_config=None):
        if repository is None:
            repository = os.getcwd()
        if not os.path.isdir(repository):
            os.makedirs(repository)

        if default_config is None:
            default_config = DEFAULT_CONFIG

        self._repository = repository
        self._config_path = os.path.join(repository, self.CONFIG_FNAME)

        if self.exists():
            # Ignore param `default_config`
            with open(self._config_path, "r") as stream:
                self._config = yaml_config_load(stream, SafeLoader)
        else:
            self._config = yaml_config_load(default_config, SafeLoader)
            self.save()

    def _get_storage_engine(self):
        """
        Get storage engine from config file,
        return default engine from default config if no config exists.
        """
        storage_cls_name = self._config.storage.engine
        module = importlib.import_module(self._config.storage.module)
        storage_cls = getattr(module, storage_cls_name)
        return storage_cls(self._repository, self._config)

    @property
    def config(self):
        return self._config

    def to_yaml(self):
        return yaml_config_dump(self._config,
                                Dumper=SafeDumper,
                                default_flow_style=False)

    def save(self):
        with open(self._config_path, "w") as stream:
            yaml_config_dump(self._config,
                             stream,
                             Dumper=SafeDumper,
                             default_flow_style=False)

    def exists(self):
        return os.path.isfile(self._config_path)

    def touched(self):
        for f in os.listdir(self._repository):
            if not f == self.CONFIG_FNAME:
                return True
        return False