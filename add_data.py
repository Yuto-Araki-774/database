import mysql.connector
from mysql.connector import Error
import pandas as pd
import re

def create_database_connection(host_name, user_name, user_password, database_name):              #データベースとコネクションを確立する関数
    connection = None
    try:
        connection = mysql.connector.connect(
            host    = host_name,
            user    = user_name,
            passwd  = user_password,
            database = database_name
        )
        print("MySQL Database connection successful")
    except Error as err:
        print(f"Error: '{err}'")

    return connection

def execute_query(connection, query):
    cursor = connection.cursor()
    try:
        cursor.execute(query)
        connection.commit()
        print("Query successful")
    except Error as err:
        print(f"Error: '{err}'")
        
def main():
    filename = input()
    
    with open(filename, 'r') as f:
        host_name     = f.readline().strip()
        user_name     = f.readline().strip()
        user_password = f.readline().strip()
        
    database_name = input()
    
    connection = create_database_connection(host_name, user_name, user_password, database_name)  #サーバーとのコネクションを確立する.
    
    
if __name__ == "__main__":
    main()