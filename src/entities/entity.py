from datetime import datetime
import cx_Oracle, os


class BackendManager:
    def __init__(self):
        self._connection = None
        self._table_names = None
        self._column_names = None
        self.get_table_names()
        self.get_column_names()
        #self.open_connection()

    def table_names(self):
        return self._table_names

    def column_names(self):
        return self._column_names

    def open_connection(self):

        #pool_min = 4
        #pool_max = 4
        #pool_inc = 0

        print("Connecting to: ", os.environ.get("PYTHON_CONNECTSTRING"))
        #self._pool = cx_Oracle.SessionPool(
        #    user=os.environ.get("PYTHON_USERNAME"),
        #    password=os.environ.get("PYTHON_PASSWORD"),
        #    dsn=os.environ.get("PYTHON_CONNECTSTRING"),
        #    min=pool_min,
        #    max=pool_max,
        #    increment=pool_inc
        #)

        user=os.environ.get("PYTHON_USERNAME")
        password=os.environ.get("PYTHON_PASSWORD")
        dsn=os.environ.get("PYTHON_CONNECTSTRING")
        testStr = "%s/%s@%s" % (user,password,dsn)
        print('Connection string: ' + testStr)
        self._connection = cx_Oracle.connect(testStr)

    def get_rows(self, query):
        print(f"INFO: Will execute: {query}")
        response = None
        with self._connection.cursor() as cursor:
            cursor.execute(query)
            response = cursor.fetchall()
        return response


    def connection_close(self):
        print(f"INFO: Closing connection")
        self._connection.close()
        return

    def get_table_names(self):
        query = "(SELECT table_name FROM all_tables WHERE table_name LIKE 'DBMAT_%') UNION (SELECT view_name FROM all_views WHERE view_name LIKE 'DBMAT_%')"
        self.open_connection()
        rows = self.get_rows(query)
        self.connection_close()
        self._table_names = [item for sublist in rows for item in sublist]

    def get_columns(self, table):
        query = f"SELECT COLUMN_NAME FROM ALL_TAB_COLUMNS WHERE TABLE_NAME = '{table}' ORDER BY COLUMN_ID"
        self.open_connection()
        rows = self.get_rows(query)
        self.connection_close()
        columns = [item for sublist in rows for item in sublist]
        return columns

    def get_column_names(self):
        self._column_names = {}
        for table in self._table_names:
            self._column_names[table]=self.get_columns(table)

    def insert(self, query):
        print(f"INFO: Will execute: {query}")
        with self._connection.cursor() as cursor:
            cursor.execute(query)
        return cursor.rowcount

    def connection_commit(self):
        print(f"INFO: Committing changes")
        self._connection.commit()
        return

    def connection_rollback(self):
        print(f"INFO: Rolling back changes")
        self._connection.rollback()
        return

