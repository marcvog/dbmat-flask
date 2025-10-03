"""
Before running, set these environment variables to connect to the database:

    PYTHON_USERNAME       - your DB username
    PYTHON_PASSWORD       - your DB password
    PYTHON_CONNECTSTRING  - the connection string to the DB,
                            e.g. "example.com/XEPDB1"
"""

import json
import logging
import os
import sys

import oracledb
from typing import Optional, Dict
from flask import jsonify, request
from svom.auth import requires_auth

from .entities.entity import BackendManager
from .entities.flask_manager import FlaskManager

log = logging.getLogger(__name__)
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

def get_environ(env_var, default_val):
    """
    Return value of environment variable {env_var} if available,
    otherwise notify in logs and return {default_val}
    """
    value = os.environ.get(env_var)
    if value is None:
        value = default_val
        msg = (
            "Empty environment variable "
            + env_var
            + ", falling back to default: {}".format(default_val)
        )
        log.warning(msg)
    return value


def get_flaskmgr():
    """
    Instantiate FlaskManager and start flask app
    """
    properties = {}
    if os.path.isfile("./config/dbmat-flask-config.json"):
        with open("./config/dbmat-flask-config.json") as json_file:
            prop_dic = json.load(json_file)
            for key in prop_dic.keys():
                log.info(f"Update property from file for key {key}")
                properties[key] = prop_dic[key]
        os.environ["PYTHON_USERNAME"] = properties["PYTHON_USERNAME"]
        os.environ["PYTHON_CONNECTSTRING"] = properties["PYTHON_CONNECTSTRING"]

    if os.path.isfile("./config/dbmat-flask-passwords.json"):
        with open("./config/dbmat-flask-passwords.json") as json_secrets:
            passwd_dic = json.load(json_secrets)
            for key in passwd_dic.keys():
                log.info(f"Update property from file for key {key}")
                properties[key] = passwd_dic[key]
        os.environ["PYTHON_PASSWORD"] = properties["PYTHON_PASSWORD"]

    log.info(f"Use config properties : {properties}")
    mgr = FlaskManager(properties=properties)
    mgr.config(properties=properties)
    return mgr


if __name__ == "__main__":
    """
    Retrieve parameters from env variables
    """
    # Retrieve info from environment variables
    flaskport = get_environ("FLASK_PORT", "5000")

    log.info(f"Flask is running on {flaskport}")
    flaskmgr = get_flaskmgr()

    # Run the service
    debug_flag = False
    if log.level <= logging.DEBUG:
        debug_flag = True
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    flaskmgr.run("0.0.0.0", flaskport, debug_flag)
else:
    log.info("Gunicorn is launching the application")
    flaskmgr = get_flaskmgr()
    gunicorn_app = flaskmgr.get_app()
    backendMgr = BackendManager()
    table_names = backendMgr.table_names()
    column_names = backendMgr.column_names() #dictonary containing all columns (list value) for each table (string key)

    def _corsify(response):
        """adds CORS headers to response"""
        response.headers.add("Access-Control-Allow-Origin", "*")
        if request.method == "OPTIONS":
            response.headers.add("Access-Control-Allow-Methods", "*")
            headers = request.headers.get("Access-Control-Request-Headers")
            if headers is not None:
                response.headers.add("Access-Control-Allow-Headers", headers)
        return response

    def add_columns(table, rows):
        log.info(f"Adding columns for table: {table}")
        response = []
        for row in rows:
            row_dict = {}
            index = 0
            for column in column_names[table]:
                if ("DATE" in column or "CREATED" in column) and row[index] is not None:
                    row_dict[column] = row[index].strftime("%Y-%m-%d %H:%M:%S")
                else:
                    row_dict[column] = row[index]
                index += 1
            response.append(row_dict)
        return response

    @flaskmgr.app.route("/api/search/", methods=["GET"])
    @requires_auth  # Check user authentication
    def get():
        table = request.args.get("table").upper()
        if table not in table_names:
            return jsonify({"message": "ERROR. Invalid table name"}), 400
        backendMgr.open_connection()
        query = f"SELECT * from ATLAS_DBMON.{table}"
        rows = backendMgr.get_rows(query)
        response = add_columns(table, rows)
        backendMgr.connection_close()
        return jsonify(response)

    @flaskmgr.app.route("/api/query/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users"])  # Check user authentication
    def query():
        query = None
        response = []
        table = (request.args.get("table") or "").upper()
        column  = (request.args.get("column") or "*").upper()
        fcolumn = request.args.get("filter_column")
        fop =  request.args.get("filter_op")
        fvalue = request.args.get("filter_value")
        orderby = (request.args.get("order") or "").upper()

        if table not in table_names:
            return jsonify({"message": "ERROR. Invalid table name"}), 400

        # Allowed columns for this table (as UPPER)
        valid_columns = [c.upper() for c in column_names[table]]
        if column != "*" and column not in valid_columns:
            return jsonify({"message": "ERROR. Invalid column name"}), 400

        if orderby not in valid_columns:
            return jsonify({"message": "ERROR. Invalid column name for sorting"}), 400

        # --- optional filter handling ---
        use_filter = fcolumn is not None or fop is not None or fvalue is not None
        where_sql = ""
        params: Optional[Dict[str, object]] = None

        if use_filter:
            # All three must be provided to form a valid filter
            if fcolumn is None or fop is None or fvalue is None:
                return jsonify({"message": "ERROR. Incomplete filter (need filter_column, filter_op, filter_value)"}), 400

            fcolumn_u = fcolumn.upper()
            if fcolumn_u not in valid_columns:
                return jsonify({"message": "ERROR. Invalid column name"}), 400

            if fop not in {"eq", "like"}:
                return jsonify({"message": "Invalid operator"}), 400

            if fop == "eq":
                where_sql += f" WHERE {fcolumn_u} = :fval"
                params = {"fval": fvalue}
            else:
                where_sql += f" WHERE {fcolumn_u} LIKE :fval ESCAPE '\\'"
                params = {"fval": fvalue}

        # --- build and run SQL ---
        select_list = "*" if column == "*" else column
        query = f"SELECT {select_list} FROM ATLAS_DBMON.{table}{where_sql} ORDER BY {orderby}"

        backendMgr.open_connection()
        try:
            rows = backendMgr.get_rows(query, params) if params is not None else backendMgr.get_rows(query)
        finally:
            backendMgr.connection_close()

        if column == "*":
            response = add_columns(table, rows)
        else:
            response = [{column: row[0]} for row in rows]

        return jsonify(response)

    @flaskmgr.app.route("/api/insert/developer/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users", "dbmat_admins"])
    def insert_developer():
        rowcount = 0
        dryrun = 1
        contact = request.args.get("contact")
        # do some checks here on the developer entry
        if contact is None:
            return jsonify({"message": "ERROR. Invalid contact"})
        dryrun = int(request.args.get("dryrun"))
        backendMgr.open_connection()
        query = (
            "INSERT INTO ATLAS_DBMON.DBMAT_DEVELOPERS (CONTACT) "
            "VALUES (:contact)"
        )
        log.info(f"Will attempt to insert developer: {contact}")
        try:
            rowcount = backendMgr.insert(query, {"contact":contact})
            log.info(f"Insertion returned a rowcount of {rowcount} affected rows")
            if rowcount == 1:
                query = (
                    "SELECT * from ATLAS_DBMON.DBMAT_DEVELOPERS "
                    "WHERE CONTACT=:contact"
                )
                rows = backendMgr.get_rows(query, {"contact": contact})
                developer_details = add_columns("DBMAT_DEVELOPERS", rows)[0]
                response = {}
                if dryrun == 1:
                    response["message"] = f"FOR COMMIT. {developer_details}"
                else:
                    backendMgr.connection_commit()
                    response["message"] = f"COMMITTED. {developer_details}"

                backendMgr.connection_close()
                return jsonify(response)

            else:
                log.info(f"Insertion failed. Number of affected rows: {rowcount}")
                response = {"message": "ERROR. No rows were inserted"}
                backendMgr.connection_rollback()
                backendMgr.connection_close()
                return jsonify(response)
        except oracledb.IntegrityError as e:
            (error_obj,) = e.args
            print("Error Code:", error_obj.code)
            print("Error Message:", error_obj.message)
            response = {"message": "ERROR. " + error_obj.message}
            backendMgr.connection_rollback()
            backendMgr.connection_close()
            return jsonify(response)

    @flaskmgr.app.route("/api/insert/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users", "dbmat_admins"])
    def insert():
        rowcount = 0
        dryrun = 1
        response = {}
        model = request.args.get("model")
        if model not in table_names:
            return jsonify({"message": "ERROR. Invalid table name"}), 400

        dryrun = int(request.args.get("dryrun"))
        backendMgr.open_connection()
        data = json.loads(request.args.get("data")) # takes JSON-encoded string and constructs a dictionary object with it
        columns = data["columns"]
        values = data["values"]

        # Allowed columns for this model (as UPPER)
        valid_columns = [c.upper() for c in column_names[model]]
        for column in columns:
            if column not in valid_columns:
                return jsonify({"message": "ERROR. Invalid column name: {column}"}), 400

        placeholders = [f":val{i}" for i in range(len(values))]
        params = {f"val{i}": values[i] for i in range(len(values))}
        query = (
            f"INSERT INTO ATLAS_DBMON.{model} "
            f"({','.join(columns)}) "
            f"VALUES ({','.join(placeholders)})"
        )
        log.info(f"Will execute the following insert statement: {query}")
        rowcount = backendMgr.insert(query, params)
        # add try-except clause to this function, make sure a list is returned
        log.info(f"Insertion returned a rowcount of {rowcount} affected rows")

        if rowcount > 0:
            clauses = []
            for idx, col in enumerate(columns):
                param = placeholders[idx]
                clauses.append(f"{col} = {param}")

            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            sql = f"SELECT * FROM ATLAS_DBMON.{model}{where}"
            rows = backendMgr.get_rows(sql, params)
            details = add_columns(model, rows)
            if dryrun == 1:
                response["message"] = f"FOR COMMIT. {details}"
            else:
                backendMgr.connection_commit()
                response["message"] = f"COMMITTED. {details}"
            backendMgr.connection_close()
            return jsonify(response)
        else:
            log.info("Isertion failed. No entries were inserted")
            response = {"message": "ERROR. No entries were inserted"}
            backendMgr.connection_rollback()
            backendMgr.connection_close()
            return jsonify(response)

    @flaskmgr.app.route("/api/delete/developer/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users", "dbmat_admins"])
    def delete_developer():
        rowcount = 0
        dryrun = 1
        response = {}
        contact = request.args.get("contact")
        # do some checks here on the developer entry
        if contact is None:
            return jsonify({"message": "ERROR. Invalid contact"})
        dryrun = int(request.args.get("dryrun"))
        backendMgr.open_connection()
        query = "SELECT * from ATLAS_DBMON.DBMAT_DEVELOPERS WHERE CONTACT=:contact"
        rows = backendMgr.get_rows(query, {"contact":contact})
        # add try-except clause to this function, make sure a list is returned
        lenrows = len(rows)
        log.info(f"Number of rows obtained from query: {lenrows}")
        if len(rows) == 1:
            developer_details = add_columns("DBMAT_DEVELOPERS", rows)[0]
            if dryrun == 1:
                response["message"] = f"FOR DELETE. {developer_details}"
            else:
                query = (
                    "DELETE from ATLAS_DBMON.DBMAT_DEVELOPERS "
                    "WHERE CONTACT=:contact"
                )
                log.info(f"Will attempt to delete developer: {contact}")
                rowcount = backendMgr.insert(query, {"contact":contact})
                # add try-except to this function, always return a number
                log.info(f"Deletion returned a rowcount of {rowcount} affected rows")
                if rowcount == 1:
                    backendMgr.connection_commit()
                    response["message"] = f"DELETED. {developer_details}"
                else:
                    backendMgr.connection_rollback()
                    response = {"message": "ERROR. Failed to delete developer"}
            backendMgr.connection_close()
            return jsonify(response)
        else:
            log.info("Deletion failed. Developer not found")
            response = {"message": "ERROR. Developer not found"}
            backendMgr.connection_close()
            return jsonify(response)

    @flaskmgr.app.route("/api/delete/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users", "dbmat_admins"])
    def delete():
        rowcount = 0
        dryrun = 1
        response = {}
        model = request.args.get("model")
        groupid = request.args.get("groupid", type=int)
        developerid = request.args.get("developerid", type=int)
        data = json.loads(request.args.get("data"))
        values = [int(v) for v in data["data"]]
        if model not in table_names:
            return jsonify({"message": "ERROR. Invalid table name"}), 400
        dryrun = int(request.args.get("dryrun"))
        backendMgr.open_connection()
        placeholders = [f":val{i}" for i in range(len(values))]
        params = {f"val{i}": values[i] for i in range(len(values))}

        if groupid is not None:
            params["groupid"] = groupid
            query = (
                "SELECT * FROM ATLAS_DBMON.DBMAT_DG2DEVS WHERE DBMDEV_ID IN "
                f"({','.join(placeholders)}) "
                "AND DBMDG_ID = :groupid"
            )
            
        if developerid is not None:
            params["developerid"] = developerid
            query = (
                "SELECT * FROM ATLAS_DBMON.DBMAT_DG2DEVS WHERE DBMDG_ID IN "
                f"({','.join(placeholders)}) "
                "AND DBMDEV_ID = :developerid"
            )
         
        rows = backendMgr.get_rows(query, params)
        if len(rows) != 0:
            details = add_columns(model, rows)
            if dryrun == 1:
                response["message"] = f"FOR DELETE. {details}"
            else:
                log.info(f"Will attempt to delete the following entries: {details}")
                if groupid is not None:
                    query = (
                        "DELETE FROM ATLAS_DBMON.DBMAT_DG2DEVS WHERE DBMDEV_ID IN "
                        f"({','.join(placeholders)}) "
                        "AND DBMDG_ID = :groupid"
                    )
                if developerid is not None:
                    query = (
                        "DELETE FROM ATLAS_DBMON.DBMAT_DG2DEVS WHERE DBMDG_ID IN "
                        f"({','.join(placeholders)}) "
                        "AND DBMDEV_ID = :developerid"
                )
                rowcount = backendMgr.insert(query, params)
                log.info(f"Deletion returned a rowcount of {rowcount} affected rows")
                if rowcount > 0:
                    # there could be a check here on the number of rows
                    backendMgr.connection_commit()
                    response["message"] = f"DELETED. {details}"
                else:
                    backendMgr.connection_rollback()
                    response = {"message": "ERROR. Failed to delete entries"}
            backendMgr.connection_close()
            return jsonify(response)
        else:
            log.info("Deletion failed. No entries found")
            response = {"message": "ERROR. No entries found"}
            backendMgr.connection_close()
            return jsonify(response)

    @flaskmgr.app.route("/api/select/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users", "dbmat_admins"])
    def select():
        query = request.args.get("query")
        model = request.args.get("model")
        backendMgr.open_connection()
        query = f"SELECT {query}"
        log.info(f"Will attempt to SELECT: {query}")
        rows = backendMgr.get_rows(query)
        response = add_columns(model, rows)
        backendMgr.connection_close()
        return jsonify(response)

    @flaskmgr.app.route("/api/groups/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users", "dbmat_admins"])
    def getAllGroups():
        query = (
            "SELECT * FROM ATLAS_DBMON.DBMAT_DEV_GROUPS " 
            "WHERE DBMDG_GROUP_NAME like 'ATLAS_%' "
            "ORDER BY DBMDG_GROUP_NAME"
        )
        backendMgr.open_connection()
        log.info(f"Will attempt to: {query}")
        rows = backendMgr.get_rows(query)
        response = add_columns("DBMAT_DEV_GROUPS", rows)
        backendMgr.connection_close()
        return jsonify(response)

    @flaskmgr.app.route("/api/developers/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users", "dbmat_admins"])
    def getAllDevelopers():
        query = (
            "SELECT * FROM ATLAS_DBMON.DBMAT_DEVELOPERS "
            "ORDER BY CONTACT_NAME"
        )
        backendMgr.open_connection()
        log.info(f"Will attempt to: {query}")
        rows = backendMgr.get_rows(query)
        response = add_columns("DBMAT_DEVELOPERS", rows)
        backendMgr.connection_close()
        return jsonify(response)

    @flaskmgr.app.route("/api/alldevsnotingroup/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users", "dbmat_admins"])
    def getAllDevsNotInGroup():
        group_id = request.args.get("group_id", type=int)
        query = (
            "SELECT * "
            "FROM ATLAS_DBMON.DBMAT_DEVELOPERS "
            "WHERE DBMDEV_ID NOT IN ("
            "    SELECT UNIQUE DBMDEV_ID "
            "    FROM ATLAS_DBMON.DBMAT_DG2DEVS "
            "    WHERE DBMDG_ID = :group_id"
            ") "
            "ORDER BY CONTACT_NAME"
        )
        backendMgr.open_connection()
        log.info(f"Will attempt to: {query}")
        rows = backendMgr.get_rows(query,{"group_id": group_id})
        response = add_columns("DBMAT_DEVELOPERS", rows)
        backendMgr.connection_close()
        return jsonify(response)

    @flaskmgr.app.route("/api/allgroupsnotindev/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users", "dbmat_admins"])
    def getAllGroupsNotInDev():
        developer_id = request.args.get("developer_id", type=int)
        query = (
            "SELECT * "
            "FROM ATLAS_DBMON.DBMAT_DEV_GROUPS "
            "WHERE DBMDG_ID NOT IN ("
            "    SELECT UNIQUE DBMDG_ID "
            "    FROM ATLAS_DBMON.DBMAT_DG2DEVS "
            "    WHERE DBMDEV_ID = :developer_id"
            ") "
            "ORDER BY DBMDG_GROUP_NAME"
        )
        backendMgr.open_connection()
        log.info(f"Will attempt to: {query}")
        rows = backendMgr.get_rows(query,{"developer_id": developer_id})
        response = add_columns("DBMAT_DEV_GROUPS", rows)
        backendMgr.connection_close()
        return jsonify(response)

    @flaskmgr.app.route("/api/alldevsingroup/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users", "dbmat_admins"])
    def getAllDevsInGroup():
        group_id = request.args.get("group_id", type=int)
        query = (
            "SELECT DISTINCT DEV.* "
            "FROM ATLAS_DBMON.DBMAT_DEVELOPERS DEV "
            "JOIN ATLAS_DBMON.DBMAT_DG2DEVS DG2DEV "
            "  ON DEV.DBMDEV_ID = DG2DEV.DBMDEV_ID "
            "WHERE DG2DEV.DBMDG_ID = :group_id "
        )
        backendMgr.open_connection()
        log.info(f"Will attempt to: {query}")
        rows = backendMgr.get_rows(query,{"group_id": group_id})
        response = add_columns("DBMAT_DEVELOPERS", rows)
        backendMgr.connection_close()
        return jsonify(response)

    @flaskmgr.app.route("/api/allgroupsindev/", methods=["GET"])
    @requires_auth(required_roles=["dbmat_users", "dbmat_admins"])
    def getAllGroupsInDev():
        developer_id = request.args.get("developer_id", type=int)
        query = (
            "SELECT DISTINCT DG.* "
            "FROM ATLAS_DBMON.DBMAT_DEV_GROUPS DG "
            "JOIN ATLAS_DBMON.DBMAT_DG2DEVS DG2DEV "
            "  ON DG.DBMDG_ID = DG2DEV.DBMDG_ID "
            "WHERE DG2DEV.DBMDEV_ID = :developer_id"
        )
        backendMgr.open_connection()
        log.info(f"Will attempt to: {query}")
        rows = backendMgr.get_rows(query,{"developer_id": developer_id})
        response = add_columns("DBMAT_DEV_GROUPS", rows)
        backendMgr.connection_close()
        
