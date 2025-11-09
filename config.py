import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-2025'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False