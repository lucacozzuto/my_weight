package com.lucacozzuto.myweight

import android.content.Context
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

object GarminAuthManager {

    private const val PREFS_NAME = "garmin_auth_secure_prefs"
    private const val KEY_DI_TOKEN = "di_token"
    private const val KEY_DI_REFRESH_TOKEN = "di_refresh_token"
    private const val KEY_JWT_WEB = "jwt_web"
    private const val KEY_CSRF_TOKEN = "csrf_token"
    private const val KEY_LAST_DATA = "cached_weight_data_json"

    private const val KEY_DI_CLIENT_ID = "di_client_id"

    private fun getPrefs(context: Context) = try {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        EncryptedSharedPreferences.create(
            context,
            PREFS_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    } catch (e: Exception) {
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    }

    fun saveTokens(
        context: Context,
        diToken: String?,
        diRefreshToken: String?,
        diClientId: String?,
        jwtWeb: String?,
        csrfToken: String?
    ) {
        val editor = getPrefs(context).edit()
        if (diToken != null) editor.putString(KEY_DI_TOKEN, diToken)
        if (diRefreshToken != null) editor.putString(KEY_DI_REFRESH_TOKEN, diRefreshToken)
        if (diClientId != null) editor.putString(KEY_DI_CLIENT_ID, diClientId)
        if (jwtWeb != null) editor.putString(KEY_JWT_WEB, jwtWeb)
        if (csrfToken != null) editor.putString(KEY_CSRF_TOKEN, csrfToken)
        editor.apply()
    }

    fun getDiToken(context: Context): String? = getPrefs(context).getString(KEY_DI_TOKEN, null)
    fun getDiRefreshToken(context: Context): String? = getPrefs(context).getString(KEY_DI_REFRESH_TOKEN, null)
    fun getDiClientId(context: Context): String? = getPrefs(context).getString(KEY_DI_CLIENT_ID, null)
    fun getJwtWeb(context: Context): String? = getPrefs(context).getString(KEY_JWT_WEB, null)
    fun getCsrfToken(context: Context): String? = getPrefs(context).getString(KEY_CSRF_TOKEN, null)

    fun hasValidAuth(context: Context): Boolean {
        val p = getPrefs(context)
        return !p.getString(KEY_DI_TOKEN, null).isNullOrBlank() || !p.getString(KEY_JWT_WEB, null).isNullOrBlank()
    }

    fun saveCachedData(context: Context, jsonData: String) {
        getPrefs(context).edit().putString(KEY_LAST_DATA, jsonData).apply()
    }

    fun getCachedData(context: Context): String? {
        return getPrefs(context).getString(KEY_LAST_DATA, null)
    }

    fun clear(context: Context) {
        getPrefs(context).edit().clear().apply()
    }
}
