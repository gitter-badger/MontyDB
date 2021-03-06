import platform

from bson.py3compat import string_type

from . import errors
from .base import BaseObject, ClientOptions
from .configure import MontyConfigure
from .database import MontyDatabase


class MontyClient(BaseObject):

    def __init__(self,
                 repository=None,
                 document_class=dict,
                 tz_aware=None,
                 **kwargs):
        """
        """
        with MontyConfigure(repository) as conf:
            self._storage = conf.load()._get_storage_engine()
        wconcern = self._storage.wconcern_parser(kwargs)

        options = kwargs
        options["document_class"] = document_class
        options["tz_aware"] = tz_aware or False
        self.__options = ClientOptions(options, wconcern)
        super(MontyClient, self).__init__(self.__options.codec_options,
                                          self.__options.write_concern)

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.address == other.address
        return NotImplemented

    def __ne__(self, other):
        return not self == other

    def __repr__(self):
        return ("MontyClient({})".format(
            ", ".join([
                "repository={!r}".format(
                    self.address
                ),
                "document_class={}.{}".format(
                    self.__options._options["document_class"].__module__,
                    self.__options._options["document_class"].__name__
                ),
                "storage_engine={}".format(
                    self._storage
                ),
            ]))
        )

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(
                "MontyClient has no attribute {0!r}. To access the {0}"
                " database, use client[{0!r}].".format(name))
        return self.get_database(name)

    def __getitem__(self, key):
        return self.get_database(key)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self._storage.is_open:
            self.close()

    @property
    def address(self):
        return self._storage.repository

    def close(self):
        self._storage.close()

    def database_names(self):
        """
        Return a list of database names.
        """
        return self._storage.database_list()

    def drop_database(self, name_or_database):
        """
        Remove database.
        # Could raise OSError: Device or resource busy
        if db file is locked by other connection...
        """
        name = name_or_database
        if isinstance(name_or_database, MontyDatabase):
            name = name_or_database.name
        elif not isinstance(name_or_database, string_type):
            raise TypeError("name_or_database must be an instance of "
                            "basestring or a Database")

        self._storage.database_drop(name)

    def get_database(self, name):
        """
        Get a database, create one if not exists.
        """
        # verify database name
        if platform.system() == "Windows":
            is_invaild = set('/\. "$*<>:|?').intersection(set(name))
        else:
            is_invaild = set('/\. "$').intersection(set(name))

        if is_invaild or not name:
            raise errors.OperationFailure("Invaild database name.")
        else:
            return MontyDatabase(self, name)
