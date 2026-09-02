from models.models import Lab, db


class LaboratoryService:

    # this function creates a new laboratory in the database
    @staticmethod
    def create_laboratory(name, location, description):
        try:
            name = name.strip()
            existing_lab = Lab.query.filter_by(name=name).first()
            if existing_lab:
                return None, "Laboratory already exists"
            new_lab = Lab(name=name, location=location, description=description)
            db.session.add(new_lab)
            db.session.commit()
            return new_lab, "Laboratory created successfully"
        except Exception as e:
            db.session.rollback()
            return None, str(e)
    #this function retrieves a laboratory by its ID from the database
    @staticmethod
    def get_laboratory_by_id(lab_id):
        try:
            lab = Lab.query.get(lab_id)
            if lab:
                return lab, "Laboratory retrieved successfully"
            else:
                return None, "Laboratory not found"
        except Exception as e:
            return None, str(e)
    #this function retrieves all laboratories from the database
    @staticmethod
    def get_all_laboratories():
        try:
            labs = Lab.query.all()
            return labs, "All laboratories retrieved successfully"
        except Exception as e:
            return None, str(e)
    #this function updates the details of a laboratory in the database
    @staticmethod
    def update_laboratory(lab_id, name=None, location=None, description=None):
        try:
            lab = Lab.query.get(lab_id)
            if not lab:
                return None, "Laboratory not found"
            if name:
                lab.name = name.strip()
            if location:
                lab.location = location
            if description:
                lab.description = description
            db.session.commit()
            return lab, "Laboratory updated successfully"
        except Exception as e:
            db.session.rollback()
            return None, str(e)            