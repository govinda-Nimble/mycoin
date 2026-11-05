from django.contrib import admin
from accounts.models import User, UserOTP


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "firstName", "lastName", "userType", "is_active", "isEmailVerified", "dateJoined")
    search_fields = ("email", "firstName", "lastName")
    list_filter = ("userType", "is_active", "isEmailVerified", "is_staff")
    readonly_fields = ("id", "dateJoined", "updatedAt")
    ordering = ("-dateJoined",)


@admin.register(UserOTP)
class UserOTPAdmin(admin.ModelAdmin):
    list_display = ("email", "user", "otp", "requestType", "isVerified", "expiresAt", "createdAt")
    search_fields = ("email", "otp", "user__email")
    list_filter = ("requestType", "isVerified", "createdAt")
    readonly_fields = ("id", "createdAt", "updatedAt")
    ordering = ("-createdAt",)
