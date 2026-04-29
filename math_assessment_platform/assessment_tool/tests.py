from django.test import TestCase
from .models import UserProfile

# class AnythingTests(TestCase):
#     def test_dummy(self):
#         pass

class UserProfileTests(TestCase):

    def test_create_student_user(self):
        # Create the student
        student = UserProfile.objects.create_student_user(
            user_email="stu@test.com", 
            username="student", 
            gender="f", 
            user_first_name="Kylee", 
            user_last_name="Sorensen", 
            password="student"
        )

        # Check if the user exists in the database
        exists = UserProfile.objects.filter(user_id=student.user_id).exists()
        self.assertTrue(exists)
        
        # Check if the formatting logic worked
        self.assertEqual(student.user_type, "Student")
        self.assertEqual(student.gender, "f")

    # def test_create_teacher_user(self):
    #     teacher = UserProfile.objects.create_teacher_user(user_email="teach@test.com", username="teacher", gender="f", user_first_name="Rachel Lee", user_last_name="McKinley", password="teacher", user_display_name="Rachel")

    #     self.assertIs(len(UserProfile(user_id=teacher.user_id))==1,True)


    # def test_create_it_support_user(self):
    #     pass

    # def test_create_parent_user(self):
    #     pass



