import mysql.connector
from mysql.connector import Error
import pandas as pd

def create_server_connection(host_name, user_name, user_password):
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


def main():
    filename = input()
    
    with open(filename, 'r') as f:
        host_name     = f.readline().strip()
        user_name     = f.readline().strip()
        user_password = f.readline().strip()
    
    conection = create_server_connection(host_name, user_name, user_password)
    
if __name__ == "__main__":
    main()
