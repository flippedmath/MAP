import re

def get_valid_unique_name(model_class, parent_obj, requested_name, field_name='name', item_type='folder'):
    # 1. Basic Validation: Alphanumeric and single internal spaces
    clean_name = requested_name.strip()
    if not clean_name or not re.match(r'^[a-zA-Z0-9]+( [a-zA-Z0-9]+)*$', clean_name):
        return None, "Names must be alphanumeric with single spaces only."

    base_name = clean_name
    new_name = clean_name
    counter = 1

    # 2. Collision Loop
    while True:
        lookup = {field_name: new_name}
        if item_type == 'folder':
            # Folders check against 'parent'
            duplicate_exists = model_class.objects.filter(parent=parent_obj, **lookup).exists()
        else:
            # Items (Course, etc) check against 'branch_location'
            duplicate_exists = model_class.objects.filter(branch_location=parent_obj, **lookup).exists()

        if not duplicate_exists:
            break
        
        new_name = f"{base_name} ({counter})"
        counter += 1
    
    return new_name, None