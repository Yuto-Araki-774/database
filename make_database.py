import mysql.connector
from mysql.connector import Error
import pandas as pd

def create_server_connection(host_name, user_name, user_password):      #MySQLとコネクションを確立する関数
    connection = None
    try:
        connection = mysql.connector.connect(
            host=host_name,
            user=user_name,
            passwd=user_password
        )
        print("MySQL Database connection successful")
    except Error as err:
        print(f"Error: '{err}'")

    return connection

def create_database(connection, database_name):                                 #データベースを作成する関数 "CREATE DATABASE aaaaa"を行う.
    cursor = connection.cursor()
    query = "CREATE DATABASE " + database_name
    try:
        cursor.execute(query)
        print("Database created successfully")
    except Error as err:
        print(f"Error: '{err}'")


def main():                                                                     #main関数 host_name, user_name, user_passwordが順に並んだテキストファイルを読み取る.
    filename = input()
    
    with open(filename, 'r') as f:
        host_name     = f.readline().strip()
        user_name     = f.readline().strip()
        user_password = f.readline().strip()
    
    connection = create_server_connection(host_name, user_name, user_password)  #サーバーとのコネクションを確立する.
    
    create_database_name = ""                                                   #ここにデータベースの名前を入力する.
    
    create_database(connection, create_database_name)
    
if __name__ == "__main__":
    main()
