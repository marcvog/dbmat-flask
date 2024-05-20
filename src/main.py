"""
Before running, set these environment variables to connect to the database:

    PYTHON_USERNAME       - your DB username
    PYTHON_PASSWORD       - your DB password
    PYTHON_CONNECTSTRING  - the connection string to the DB, e.g. "example.com/XEPDB1"
"""
import os, sys, json
import logging

from .entities.entity import BackendManager
from .entities.flask_manager import FlaskManager
from flask import redirect, request, jsonify, session, Response
import cx_Oracle

from svom.auth import (
    requires_auth
)

from keycloak import Client

log = logging.getLogger(__name__)
logging.basicConfig(stream=sys.stdout, level=logging.INFO, \
                    format='%(asctime)s %(levelname)s [%(name)s] %(message)s')
log.write = lambda msg: log.error(msg.strip()) if msg.strip() else None
log.flush = lambda: None
sys.stderr = log


def get_environ(env_var, default_val):
    """
    Return value of environment variable {env_var} if available,
    otherwise notify in logs and return {default_val}
    """
    value = os.environ.get(env_var)
    if value is None:
        value = default_val
        msg = 'Empty environment variable ' + env_var \
              + ', falling back to default: {}'.format(default_val)
        log.warning(msg)
    return value

def get_flaskmgr():
    """
    Instantiate FlaskManager and start flask app
    """
    # secrets
    if os.path.isfile('/run/secrets/DBMAT_CLIENT_SECRET'):
        with open('/run/secrets/DBMAT_CLIENT_SECRET') as key:
           line = key.readline().rstrip('\n')
           os.environ["DBMAT_CLIENT_SECRET"] = line

    # properties
    properties = {'CLIENT_SECRET': get_environ('DBMAT_CLIENT_SECRET', 'none')
                 }

    if os.path.isfile('./config/dbmat-config.json'):
        with open('./config/dbmat-config.json') as json_file:
            prop_dic = json.load(json_file)
            for key in prop_dic.keys():
                log.info(f'Update property from file for key {key}')
                properties[key] = prop_dic[key]

    if os.path.isfile('./config/DBMAT_SCHEMA_PASSWDS'):
        with open('./config/DBMAT_SCHEMA_PASSWDS') as json_secrets:
            passwd_dic = json.load(json_secrets)
            for key in passwd_dic.keys():
                log.info(f'Update property from file for key {key}')
                properties[key] = passwd_dic[key]

    log.info(f'Use config properties : {properties}')
    mgr = FlaskManager(properties=properties)
    mgr.config(properties=properties)
    return mgr

if __name__ == '__main__':
    """
    Retrieve parameters from env variables
    """
    # Retrieve info from environment variables
    flaskport = get_environ('FLASK_PORT', '5000')

    log.info(f'Flask is running on {flaskport}')
    flaskmgr = get_flaskmgr()

    # Run the service
    debug_flag = False
    if log.level <= logging.DEBUG:
        debug_flag = True
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    flaskmgr.run('0.0.0.0', flaskport, debug_flag)
else:
    log.info(f'Gunicorn is launching the application')
    flaskmgr = get_flaskmgr()
    gunicorn_app = flaskmgr.get_app()
    backendMgr = BackendManager()
    table_names = backendMgr.table_names()
    column_names = backendMgr.column_names()

    def _corsify(response):
        """ adds CORS headers to response """
        response.headers.add('Access-Control-Allow-Origin', '*')
        if request.method == 'OPTIONS':
            response.headers.add('Access-Control-Allow-Methods', '*')
            headers = request.headers.get('Access-Control-Request-Headers')
            if headers is not None:
                response.headers.add('Access-Control-Allow-Headers', headers)
        return response


    #@flaskmgr.app.route('/columns/', methods=['GET'])
    #def get_columns():
    #    table = request.args.get('table').upper()
    #    return backendMgr.get_columns(table)


    def add_columns(table, rows):
        log.info(f'Adding columns for table: {table}')
        response = []
        for row in rows:
            row_dict = {}
            index = 0
            for column in column_names[table]:
                if ('DATE' in column or 'CREATED' in column) and row[index] != None:
                    row_dict[column] = row[index].strftime('%Y-%m-%d %H:%M:%S')
                else:
                    row_dict[column] = row[index]
                index +=1
            response.append(row_dict)
        return response


    @flaskmgr.app.route('/search/', methods=['GET'])
    @requires_auth          # Check user authentication
    def get():
        table = request.args.get('table').upper()
        backendMgr.open_connection()
        query = "SELECT * from ATLAS_DBMON." + table
        rows = backendMgr.get_rows(query)
        response = add_columns(table, rows)
        backendMgr.connection_close()
        return jsonify(response)
        #return _corsify(jsonify(dbresult))


    @flaskmgr.app.route('/query/', methods=['GET'])
    @requires_auth(required_roles=['default-role']) # Check user authentication
    def query():
        query = None
        response = []
        column = request.args.get('column')
        table = request.args.get('table').upper()
        where = request.args.get('where')
        orderby = request.args.get('order')
        backendMgr.open_connection()
        if where is not None:
            query = f"SELECT {column} from ATLAS_DBMON.{table} WHERE {where} ORDER BY {orderby}"
        else:
            query = f"SELECT {column} from ATLAS_DBMON.{table} ORDER BY {orderby}"
        rows = backendMgr.get_rows(query)
        response = []
        if column == '*':
            response = add_columns(table, rows)
        else:
            for row in rows:
                row_dict = {}
                row_dict[column] = row[0]
                response.append(row_dict)
        backendMgr.connection_close()
        return jsonify(response)


    @flaskmgr.app.route('/insert/developer', methods=['GET'])
    @requires_auth(required_roles=['default-role', 'dbmat_admins'])
    def insert_developer():
        rowcount=0
        dryrun=1
        response = {"message": "ERROR. No rows were inserted"}
        contact = request.args.get('contact')
        #do some checks here on the developer entry
        dryrun = int(request.args.get('dryrun'))
        backendMgr.open_connection()
        query = f"INSERT INTO ATLAS_DBMON.DBMAT_DEVELOPERS (CONTACT) VALUES ('{contact}')"
        log.info(f'Will attempt to insert developer: {contact}')
        try:
            rowcount = backendMgr.insert(query)
            log.info(f'Insertion returned a rowcount of {rowcount} affected rows')
            if rowcount == 1:
                query = f"SELECT * from ATLAS_DBMON.DBMAT_DEVELOPERS WHERE CONTACT='{contact}'"
                rows = backendMgr.get_rows(query)
                developer_details = add_columns('DBMAT_DEVELOPERS', rows)[0]
                dev_id = rows[0][0]
                dev = rows[0][1]
                insert_date = rows[0][2]
                update_date = rows[0][3]
                name = rows[0][4]
                email = rows[0][5]

                if dryrun == 1:
                    response["message"]=f'FOR COMMIT. {developer_details}'
                else:
                    backendMgr.connection_commit()
                    response["message"]=f'COMMITTED. {developer_details}'

                backendMgr.connection_close()
                return jsonify(response)

            else:
                log.info(f'Insertion failed. Number of affected rows: {rowcount}')
                response = {"message": "ERROR. No rows were inserted"}
                backendMgr.connection_rollback()
                backendMgr.connection_close()
                return jsonify(response)
        except cx_Oracle.IntegrityError as e:
            error_obj, = e.args
            print("Error Code:", error_obj.code)
            print("Error Message:", error_obj.message)
            response = {"message": "ERROR. "+ error_obj.message}
            backendMgr.connection_rollback()
            backendMgr.connection_close()
            return jsonify(response)

    @flaskmgr.app.route('/insert/', methods=['GET'])
    @requires_auth(required_roles=['default-role', 'dbmat_admins'])
    def insert():
        rowcount=0
        dryrun=1
        response = {}
        model = request.args.get('model')
        dryrun = int(request.args.get('dryrun'))
        backendMgr.open_connection()
        data = json.loads(request.args.get('query'))
        columns = ','.join(data['columns'])
        values = ','.join(data['values'])
        query = 'INSERT INTO ATLAS_DBMON.'+model+' ('+columns+') VALUES ('+values+')'
        log.info(f'Will execute the following insert statement: {query}')
        rowcount = backendMgr.insert(query) #add try-except clause to this function, make sure a list is returned
        log.info(f'Insertion returned a rowcount of {rowcount} affected rows')
        if rowcount > 0:
            where = ' WHERE '
            for index in range(len(data['columns'])):
               if index == len(data['columns']) - 1:
                   where += data['columns'][index] + " = '" + data['values'][index] + "'"
               else:
                   where += data['columns'][index] + " = '" + data['values'][index] + "' AND "
            rows = backendMgr.get_rows('SELECT * FROM ATLAS_DBMON.'+model+where)
            details = add_columns(model, rows)
            if dryrun == 1:
                response["message"]=f'FOR COMMIT. {details}'
            else:
                backendMgr.connection_commit()
                response["message"]=f'COMMITTED. {details}'
            backendMgr.connection_close()
            return jsonify(response)
        else:
            log.info(f'Isertion failed. No entries were inserted')
            response = {"message": "ERROR. No entries were inserted"}
            backendMgr.connection_rollback()
            backendMgr.connection_close()
            return jsonify(response)


    @flaskmgr.app.route('/delete/developer', methods=['GET'])
    @requires_auth(required_roles=['default-role', 'dbmat_admins'])
    def delete_developer():
        rowcount=0
        dryrun=1
        response = {}
        contact = request.args.get('contact')
        #do some checks here on the developer entry
        dryrun = int(request.args.get('dryrun'))
        backendMgr.open_connection()
        query = f"SELECT * from ATLAS_DBMON.DBMAT_DEVELOPERS WHERE CONTACT='{contact}'"
        rows = backendMgr.get_rows(query) #add try-except clause to this function, make sure a list is returned
        if len(rows) == 1:
            developer_details = add_columns('DBMAT_DEVELOPERS', rows)[0]
            if dryrun == 1:
                response["message"]=f'FOR DELETE. {developer_details}'
            else:
                query = f"DELETE from ATLAS_DBMON.DBMAT_DEVELOPERS WHERE CONTACT='{contact}'"
                log.info(f'Will attempt to delete developer: {contact}')
                rowcount = backendMgr.insert(query) #add try-except clause to this function (change it for dml), always return a number
                log.info(f'Deletion returned a rowcount of {rowcount} affected rows')
                if rowcount == 1:
                    backendMgr.connection_commit()
                    response["message"]=f'DELETED. {developer_details}'
                else:
                    backendMgr.connection_rollback()
                    response = {"message": "ERROR. Failed to delete developer"}
            backendMgr.connection_close()
            return jsonify(response)
        else:
            log.info(f'Deletion failed. Developer not found')
            response = {"message": "ERROR. Developer not found"}
            backendMgr.connection_close()
            return jsonify(response)


    @flaskmgr.app.route('/delete/', methods=['GET'])
    @requires_auth(required_roles=['default-role', 'dbmat_admins'])
    def delete():
        rowcount=0
        dryrun=1
        response = {}
        model = request.args.get('model')
        #query = request.args.get('query')
        dryrun = int(request.args.get('dryrun'))
        backendMgr.open_connection()
        #query = f'SELECT * {query}'
        rows = backendMgr.get_rows('SELECT * ' + request.args.get('query')) #add try-except clause to this function, make sure a list is returned
        if len(rows) != 0:
            details = add_columns(model, rows)
            if dryrun == 1:
                response["message"]=f'FOR DELETE. {details}'
            else:
                #query = f'DELETE {query}'
                log.info(f'Will attempt to delete the following entries: {details}')
                rowcount = backendMgr.insert('DELETE ' + request.args.get('query')) #add try-except clause to this function (change it for dml), always return a number
                log.info(f'Deletion returned a rowcount of {rowcount} affected rows')
                if rowcount > 0: #there could be a check here on the number of rows
                    backendMgr.connection_commit()
                    response["message"]=f'DELETED. {details}'
                else:
                    backendMgr.connection_rollback()
                    response = {"message": "ERROR. Failed to delete entries"}
            backendMgr.connection_close()
            return jsonify(response)
        else:
            log.info(f'Deletion failed. No entries found')
            response = {"message": "ERROR. No entries found"}
            backendMgr.connection_close()
            return jsonify(response)


    @flaskmgr.app.route('/select/', methods=['GET'])
    @requires_auth(required_roles=['default-role', 'dbmat_admins'])
    def select():
        query = request.args.get('query')
        model = request.args.get('model')
        backendMgr.open_connection()
        query = f"SELECT {query}"
        log.info(f'Will attempt to SELECT: {query}')
        rows = backendMgr.get_rows(query)
        response = add_columns(model, rows)
        backendMgr.connection_close()
        return jsonify(response)

    @flaskmgr.app.route('/dml/', methods=['GET'])
    @requires_auth(required_roles=['default-role', 'dbmat_admins'])
    def dml():

        dryrun=1 #do not commit
        rowcount=0
        response = {'message': ''}
        query = request.args.get('query')
        model = request.args.get('model')
        dryrun = int(request.args.get('dryrun'))

        backendMgr.open_connection()
        log.info(f'Will attempt to: {query}')
        rowcount = backendMgr.insert(query) # here you need a try, except clause
        if rowcount != 1: # integrate with the try
            response["message"]=f'report error'

        if dryrun == 0: #do commit
            backendMgr.connection_commit()
            response["message"]=f'report done'
        else:
            response["message"]=f'report posible'

        backendMgr.connection_close()
        return jsonify(response)


