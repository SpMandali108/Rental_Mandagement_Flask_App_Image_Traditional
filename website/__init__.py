from flask import Flask
from pymongo import MongoClient
from dotenv import load_dotenv
import re
import os


load_dotenv()

def create_app():
    app = Flask(__name__)
    app.jinja_env.filters['regex_replace'] = lambda s, pat, repl: re.sub(pat, repl, s)
    app.config['SECRET_KEY'] = os.environ.get("key")
    from .views import views
    from .auth import auth  

    app.register_blueprint(views, url_prefix='/')
    app.register_blueprint(auth, url_prefix='/')
    
    return app

