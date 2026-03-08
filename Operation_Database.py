import mysql.connector as sqlconn
from mysql.connector import Error
import pandas as pd
import re

class DB_Manager:                                   #データベースの基本操作を行うクラス
    def __init__(self, DB_path):                    #DB_path...[host, user, passwd]
        self.connection     = None
        self.cursor         = None
        self.DB_name        = None
        self.table_name     = None
        self.columns        = None
        self.primary_keys   = "id"
        self.connect(DB_path)
        
    def connect(self, DB_path):                     #データベースとのコネクションを確立する関数
        try:
            self.connection = sqlconn.connect(
                host  = DB_path[0],
                user  = DB_path[1],
                passwd= DB_path[2]
            )
            if self.connection.is_connected():
                print("MySQL Database connection successful")
                self.cursor = self.connection.cursor(dictionary=True)
        
        except Error as err:
            print(f'Connection error: {err}')
                
    def close(self):                                #データベースとのコネクションを閉じる関数 作業終了時必ず実行させること
        if  self.connection.is_connected():
            self.cursor.close()
            self.connection.close()
            print("MySQL Database connection closed")
    
    def Create_Table(self, table_name, columns, primary_key="id"):#テーブルを作る関数
        self.table_name = table_name
        self.columns    = columns
        self.primary_key = primary_key

        if not re.fullmatch(r'\w+', table_name):
            print("please input name")
            return False
        
        query = f"CREATE TABLE {table_name} ("
        
        for column in columns:
            query += f"{column} VARCHAR(255), "
        
        query += f"PRIMARY KEY ({self.primary_key}))"
        
        try:
            self.cursor.execute(query)
            print("Table created successfully")
            return True
        except Error as err:
            print(f"Error: '{err}'")
            return False
        
    def Get_Primary_Key(self):                       #テーブルの主キーを得る関数
        if self.table_name == None:
            print("Please select table")
            return None
        
        query = f"SHOW KEYS FROM {self.table_name} WHERE Key_name = 'PRIMARY'"
        self.cursor.execute(query)
        rows = self.cursor.fetchall()
        return [row['Column_name'] for row in rows]
        
        
    
    def Select_Table(self, table_name):             #テーブルを選択する関数 いらないかも
        self.table_name = table_name
        query = f"SELECT * FROM {table_name}"
        try:
            self.cursor.execute(query)
            self.columns = [i[0] for i in self.cursor.description]
            self.primary_keys = self.Get_Primary_Key()
            return self.cursor.fetchall()
        
        except Error as err:
            print(f"Error: '{err}'")
            return None
        
        
    def Insert_Data(self, data):                    #テーブルにデータを挿入する関数
        if self.table_name == None or self.columns == None:
            print("please select table")
            return False
        
        if len(data) != len(self.columns):
            print("data length does not match column length")
            return False
        
        query = f"""
        INSERT INTO {self.table_name} ({', '.join(self.columns)})
        VALUES ({', '.join(['%s'] * len(self.columns))})
        """
        
        try:
            self.cursor.execute(query)
            self.connection.commit()
            print("Data inserted successfully")
            return True
        except Error as err:
            print(f"Error: '{err}'")
            return False
        
    def Delete_Data(self, Condition):               #テーブルからデータを削除する関数 ConditionはSQLのWHERE句の条件式
        if self.table_name == None:
            print("please select table")
            return False
        
        query = f"DELETE FROM {self.table_name} WHERE {Condition}"
        
        try:
            self.cursor.execute(query)
            self.connection.commit()
            print("Data deleted successfully")
            return True
        except Error as err:
            print(f"Error: '{err}'")
            return False
    
    def Update_Data(self, Set, Condition):          #テーブルのデータを更新する関数 SetはSQLのSET句の内容 ConditionはSQLのWHERE句の条件式
        if self.table_name == None:
            print("please select table")
            return False
        
        query = f"UPDATE {self.table_name} SET {Set} WHERE {Condition}"
        
        try:
            self.cursor.execute(query)
            self.connection.commit()
            print("Data updated successfully")
            return True
        except Error as err:
            print(f"Error: '{err}'")
            return False
        
    def Get_Data(self, Columns="*", Condition = None):           #テーブルからデータを取得する関数 ConditionはSQLのWHERE句の条件式 条件なしで全てのデータを取得することも可能
        if self.table_name == None:
            print("please select table")
            return None
        
        query = f"SELECT {Columns} FROM {self.table_name}"
        if Condition != None:
            query += f" WHERE {Condition}"
            
        try:
            self.cursor.execute(query)
            return self.cursor.fetchall()
        except Error as err:
            print(f"Error: '{err}'")
            return None
        
    
        
        