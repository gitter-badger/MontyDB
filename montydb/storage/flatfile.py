
import os
import shutil
from itertools import islice
from bson import BSON, SON
from bson.py3compat import _unicode
from bson.json_util import (
    CANONICAL_JSON_OPTIONS,
    loads as _loads,
    dumps as _dumps,
)

from .abcs import (
    StorageConfig,
    AbstractStorage,
    AbstractDatabase,
    AbstractCollection,
    AbstractCursor,
)


FALTFILE_CONFIG = """
storage:
  engine: FlatFileStorage
  config: FlatFileConfig
  module: {}
connection:
  cache_modified: 0
""".format(__name__)


FLATFILE_CONFIG_SCHEMA = """
type: object
required:
    - connection
properties:
  connection:
    type: object
    required:
        - cache_modified
    properties:
      cache_modified:
        type: integer
        minimum: 0
"""


class FlatFileConfig(StorageConfig):
    """FaltFile storage configuration settings

    Default configuration and schema of FaltFile storage
    """
    config = FALTFILE_CONFIG
    schema = FLATFILE_CONFIG_SCHEMA


FLATFILE_DB_EXT = ".json"


# (TODO) CANONICAL_JSON_OPTIONS might need to sync with codec_options


def _read_pretty(file_path):
    with open(file_path, "r") as fp:
        lines = [line.strip() for line in fp.readlines()]
        if lines:
            serialized = "".join(lines)
            return _loads(serialized, json_options=CANONICAL_JSON_OPTIONS)
        else:
            return []


def _write_pretty(file_path, documents):
    serialized = []
    for doc in documents.values():
        serialized.append(
            _dumps(BSON(doc).decode(), json_options=CANONICAL_JSON_OPTIONS))

    with open(file_path, "w") as fp:
        fp.write("[\n{}\n]".format(",\n".join(serialized)))


class FlatFileKVEngine(object):

    def __init__(self, file_path, conn_config):
        """
        """
        self.file_path = file_path

        self.__conn_config = conn_config
        self.__cache = SON()
        self.modified_count = 0

        if os.path.isfile(self.file_path):
            for doc in _read_pretty(self.file_path):
                self.__cache[doc["_id"]] = BSON.encode(doc)

    @classmethod
    def touch(cls, file_path):
        if not os.path.isfile(file_path):
            with open(file_path, "w"):
                pass

    @property
    def document_count(self):
        return len(self.__cache)

    def flush(self):
        _write_pretty(self.file_path, self.__cache)
        self.modified_count = 0

    def read(self):
        return self.__cache

    def write(self, documents):
        if not isinstance(documents, SON):
            raise TypeError("Expecting 'SON' type, got {!r}"
                            "".format(type(documents).__name__))
        self.modified_count += len(documents)
        self.__cache.update(documents)

        if self.modified_count > self.__conn_config.cache_modified:
            self.flush()

    def delete(self, doc_id):
        self.modified_count += 1
        del self.__cache[doc_id]

        if self.modified_count > self.__conn_config.cache_modified:
            self.flush()


class FlatFileStorage(AbstractStorage):
    """
    """

    def __init__(self, repository, storage_config):
        super(FlatFileStorage, self).__init__(repository, storage_config)
        self._init_cache_manager()

    def _init_cache_manager(self):
        self._cache_manager = {}

    def _db_path(self, db_name):
        """
        Get Monty database dir path.
        """
        return os.path.join(self._repository, db_name)

    def close(self):
        for db in self._cache_manager:
            for col in self._cache_manager[db]:
                self._cache_manager[db][col].flush()
        self._init_cache_manager()
        self.is_opened = False

    def database_create(self, db_name):
        if not os.path.isdir(self._db_path(db_name)):
            os.makedirs(self._db_path(db_name))

    def database_drop(self, db_name):
        db_path = self._db_path(db_name)
        if os.path.isdir(db_path):
            shutil.rmtree(db_path)
        if db_name in self._cache_manager:
            del self._cache_manager[db_name]

    def database_list(self):
        return [
            name for name in os.listdir(_unicode(self._repository))
            if os.path.isdir(self._db_path(name))
        ]


class FlatFileDatabase(AbstractDatabase):
    """
    """

    def __init__(self, storage, subject):
        super(FlatFileDatabase, self).__init__(storage, subject)
        if self._name not in storage._cache_manager:
            storage._cache_manager[self._name] = {}
        self._db_path = storage._db_path(self._name)

    @property
    def _cache_manager(self):
        return self._storage._cache_manager[self._name]

    def _col_path(self, col_name):
        """
        Get JSON database file path, which is Monty collection.
        """
        return os.path.join(self._db_path, col_name) + FLATFILE_DB_EXT

    def database_exists(self):
        return os.path.isdir(self._db_path)

    def collection_exists(self, col_name):
        return os.path.isfile(self._col_path(col_name))

    def collection_create(self, col_name):
        if not self.database_exists():
            self._storage.database_create(self._name)
        FlatFileKVEngine.touch(self._col_path(col_name))

    def collection_drop(self, col_name):
        if self.collection_exists(col_name):
            os.remove(self._col_path(col_name))
        if col_name in self._cache_manager:
            del self._cache_manager[col_name]

    def collection_list(self):
        if not self.database_exists():
            return []
        return [os.path.splitext(name)[0]
                for name in os.listdir(_unicode(self._db_path))]


FlatFileStorage.contractor_cls = FlatFileDatabase


class FlatFileCollection(AbstractCollection):
    """
    """

    def __init__(self, database, subject):
        config = database._storage._config
        super(FlatFileCollection, self).__init__(database, subject)

        self._col_path = self._database._col_path(self._name)
        if self._name not in database._cache_manager:
            database._cache_manager[self._name] = FlatFileKVEngine(
                self._col_path, config.connection)

    @property
    def _flatfile(self):
        return self._database._cache_manager[self._name]

    def _ensure_table(func):
        def make_table(self, *args, **kwargs):
            if not self._database.collection_exists(self._name):
                self._database.collection_create(self._name)
            return func(self, *args, **kwargs)
        return make_table

    @_ensure_table
    def write_one(self, doc):
        _doc = SON()
        _doc[doc["_id"]] = self._encode_doc(doc)
        self._flatfile.write(_doc)

        return doc["_id"]

    @_ensure_table
    def write_many(self, docs, ordered=True):
        _docs = SON()
        for doc in docs:
            _docs[doc["_id"]] = self._encode_doc(doc)

        self._flatfile.write(_docs)

        return [doc["_id"] for doc in docs]

    def update_one(self, doc):
        self.write_one(doc)

    def update_many(self, docs):
        self.write_many(docs)


FlatFileDatabase.contractor_cls = FlatFileCollection


class FlatFileCursor(AbstractCursor):
    """
    """

    def __init__(self, collection, subject):
        super(FlatFileCursor, self).__init__(collection, subject)

    @property
    def _flatfile(self):
        return self._collection._flatfile

    def query(self, max_scan):
        cache = self._flatfile.read()
        docs = (self._decode_doc(doc) for doc in cache.values())
        if not max_scan:
            return docs
        else:
            return islice(docs, max_scan)


FlatFileCollection.contractor_cls = FlatFileCursor
