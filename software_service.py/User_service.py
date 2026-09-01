from models.models import User, db
from flask_login import login_user, logout_user, current_user


class UserService:
    #this function creates a new user in the database
    @staticmethod
    def create_user(name, password):
      try:
        name=name.strip().lower()
        existing_user = User.query.filter_by(name=name).first()
        if existing_user:
            return None, "User already exists"
        new_user = User(name=name, password=password)
        db.session.add(new_user)
        db.session.commit()
        return new_user, "user created successfully"
      except Exception as e:
        db.session.rollback()
        return None, str(e)
    #this function authenticates a user by checking the provided name and password against the database
    @staticmethod
    def authenticate_user(name, password):
        try:
            name=name.strip().lower()
            user = User.query.filter_by(name=name).first()
            if user and user.password == password:
                login_user(user)
                return user, "تم تسجيل الدخول بنجاح"
            else:
                return None, "اسم المستخدم أو كلمة المرور غير صحيحة"
        except Exception as e:
            return None, str(e)
    #this function logs out the current user
    @staticmethod
    def logout_user():
        logout_user()
        return "تم تسجيل الخروج بنجاح"
    #this function retrieves the currently logged-in user
    @staticmethod
    def get_current_user():
        if current_user.is_authenticated:
            return current_user
        else:
            return None
    #this function retrieves all users from the database    
    @staticmethod
    def get_all_users():
        try:
            users = User.query.all()
            return users, "تم جلب جميع المستخدمين بنجاح"
        except Exception as e:
            return None, str(e)    