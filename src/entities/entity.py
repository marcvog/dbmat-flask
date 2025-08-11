import os
import oracledb


class BackendManager:
    def __init__(self):
        self._connection = None
        self._table_names = None
        self._column_names = None
        self.get_table_names()
        self.get_column_names()
        # self.open_connection()

    def table_names(self):
        return self._table_names

    def column_names(self):
        return self._column_names

    def open_connection(self):

        # pool_min = 4
        # pool_max = 4
        # pool_inc = 0

        print("Connecting to: ", os.environ.get("PYTHON_CONNECTSTRING"))
        # self._pool = oracledb.SessionPool(
        #    user=os.environ.get("PYTHON_USERNAME"),
        #    password=os.environ.get("PYTHON_PASSWORD"),
        #    dsn=os.environ.get("PYTHON_CONNECTSTRING"),
        #    min=pool_min,
        #    max=pool_max,
        #    increment=pool_inc
        # )

        oracledb.init_oracle_client()
        user = os.environ.get("PYTHON_USERNAME")
        password = os.environ.get("PYTHON_PASSWORD")
        dsn = os.environ.get("PYTHON_CONNECTSTRING")
        testStr = "%s/%s@%s" % (user, password, dsn)
        print("Connection string: " + testStr)
        self._connection = oracledb.connect(testStr)

    def get_rows(self, query):
        print(f"INFO: Will execute: {query}")
        response = None
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            response = cursor.fetchall()
        return response

    def connection_close(self):
        print("INFO: Closing connection")
        self._connection.close()
        return

    def get_table_names(self) -> list[str]:
        query = (
            "(SELECT table_name FROM all_tables "
            "WHERE table_name LIKE 'DBMAT_%') "
            "UNION "
            "(SELECT view_name FROM all_views "
            "WHERE view_name LIKE 'DBMAT_%')"
        )
        self.open_connection()
        try:
            rows = self.get_rows(query)
        finally:
            self.connection_close()
        names = [row[0] for row in rows]
        self._table_names = names
        return names

    def get_columns(self, table) -> list[str]:
        query = (
            "SELECT COLUMN_NAME FROM USER_TAB_COLUMNS "
            f"WHERE TABLE_NAME = '{table}' "
            "ORDER BY COLUMN_ID"
        )
        self.open_connection()
        try:
            rows = self.get_rows(query)
        finally:
            self.connection_close()
        columns = [row[0] for row in rows]
        return columns

    def get_column_names(self):
        self._column_names = {}
        for table in self._table_names:
            self._column_names[table] = self.get_columns(table)

    def insert(self, query):
        print(f"INFO: Will execute: {query}")
        with self._connection.cursor() as cursor:
            cursor.execute(query)
        return cursor.rowcount

    def connection_commit(self):
        print("INFO: Committing changes")
        self._connection.commit()
        return

    def connection_rollback(self):
        print("INFO: Rolling back changes")
        self._connection.rollback()
        return
