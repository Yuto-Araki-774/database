import mysql.connector
from mysql.connector import Error
import pandas as pd

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
    
    create_series_table = """
    CREATE TABLE `series`(
        series_id INT PRIMARY KEY,
        parent_series_id INT,
        series_name VARCHAR(80) NOT NULL,
        total_volumes INT NOT NULL,
        latest_volume_number INT NOT NULL,
        latest_volume_date DATE NOT NULL,
        is_completed BOOL NOT NULL,
        has_missing_volumes BOOL NOT NULL
    );
    """
    
    create_not_owned_table = """
    CREATE TABLE `not_owned`(
        series_id INT NOT NULL,
        volume_number INT NOT NULL,
        is_released BOOL NOT NULL,
        released_date DATE NOT NULL,
        PRIMARY KEY(series_id, volume_number),
        FOREIGN KEY(series_id) REFERENCES series(series_id) ON DELETE CASCADE
    );
    """
    
    execute_query(connection, create_series_table)
    
    execute_query(connection, create_not_owned_table)
    
if __name__ == "__main__":
    main()