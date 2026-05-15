# Even with the best signals, sometimes a server crash or an interrupted transaction 
#    can leave a file behind. Every few months, it's a good idea to run a quick script 
#    to find "orphaned" files (files in the folder that aren't mentioned in the database).

# A conceptual logic for an orphan-cleanup script
from django.core.files.storage import default_storage
from assessment_tool.models import Course

def cleanup_orphaned_images():
    # Get all files in the directory
    files_on_disk = default_storage.listdir('course_images/')[1]
    # Get all filenames referenced in DB
    files_in_db = set(Course.objects.values_list('image', flat=True))
    
    for file in files_on_disk:
        if f"course_images/{file}" not in files_in_db:
            default_storage.delete(f"course_images/{file}")