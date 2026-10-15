package com.lucacozzuto.myweight

import android.content.Context
import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.FormBody
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Calendar
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit
import kotlin.math.roundToInt

object GarminDataFetcher {

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private val DI_CLIENT_IDS = listOf(
        "GARMIN_CONNECT_MOBILE_ANDROID_DI_2025Q2",
        "GARMIN_CONNECT_MOBILE_ANDROID_DI_2024Q4",
        "GARMIN_CONNECT_MOBILE_ANDROID_DI",
        "GARMIN_CONNECT_MOBILE_IOS_DI"
    )

    private const val DI_TOKEN_URL = "https://diauth.garmin.com/di-oauth2-service/oauth/token"
    private const val DI_GRANT_TYPE = "https://connectapi.garmin.com/di-oauth2-service/oauth/grant/service_ticket"
    private const val PORTAL_SERVICE_URL = "https://connect.garmin.com/app"

    suspend fun exchangeTicketForToken(context: Context, ticket: String): Boolean = withContext(Dispatchers.IO) {
        for (clientId in DI_CLIENT_IDS) {
            try {
                val basicAuth = "Basic " + Base64.encodeToString("$clientId:".toByteArray(), Base64.NO_WRAP)
                val body = FormBody.Builder()
                    .add("client_id", clientId)
                    .add("service_ticket", ticket)
                    .add("grant_type", DI_GRANT_TYPE)
                    .add("service_url", PORTAL_SERVICE_URL)
                    .build()

                val request = Request.Builder()
                    .url(DI_TOKEN_URL)
                    .header("Authorization", basicAuth)
                    .header("Accept", "application/json")
                    .header("User-Agent", "GCM-Android-5.0")
                    .post(body)
                    .build()

                val resp = httpClient.newCall(request).execute()
                val respStr = resp.body?.string() ?: ""
                if (resp.isSuccessful) {
                    val json = JSONObject(respStr)
                    val diToken = json.optString("access_token", null)
                    val diRefresh = json.optString("refresh_token", null)
                    if (!diToken.isNullOrBlank()) {
                        GarminAuthManager.saveTokens(context, diToken, diRefresh, clientId, null, null)
                        return@withContext true
                    }
                }
            } catch (e: Exception) {
                e.printStackTrace()
            }
        }
        return@withContext false
    }

    private fun refreshDiToken(context: Context): Boolean {
        val refreshToken = GarminAuthManager.getDiRefreshToken(context)
        val clientId = GarminAuthManager.getDiClientId(context) ?: DI_CLIENT_IDS.first()
        if (refreshToken.isNullOrBlank()) return false

        try {
            val basicAuth = "Basic " + Base64.encodeToString("$clientId:".toByteArray(), Base64.NO_WRAP)
            val body = FormBody.Builder()
                .add("client_id", clientId)
                .add("refresh_token", refreshToken)
                .add("grant_type", "refresh_token")
                .build()

            val request = Request.Builder()
                .url(DI_TOKEN_URL)
                .header("Authorization", basicAuth)
                .header("Accept", "application/json")
                .header("User-Agent", "GCM-Android-5.0")
                .post(body)
                .build()

            val resp = httpClient.newCall(request).execute()
            if (resp.isSuccessful) {
                val json = JSONObject(resp.body?.string() ?: "")
                val newDiToken = json.optString("access_token", null)
                val newRefresh = json.optString("refresh_token", refreshToken)
                if (!newDiToken.isNullOrBlank()) {
                    GarminAuthManager.saveTokens(context, newDiToken, newRefresh, clientId, null, null)
                    return true
                }
            }
        } catch (e: Exception) {
            e.printStackTrace()
        }
        return false
    }

    suspend fun fetchWeightHistory(context: Context): String = withContext(Dispatchers.IO) {
        var diToken = GarminAuthManager.getDiToken(context)
        val jwtWeb = GarminAuthManager.getJwtWeb(context)

        val cal = Calendar.getInstance()
        val endStr = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(cal.time)
        // Default start date: 180 days ago
        cal.add(Calendar.DAY_OF_YEAR, -180)
        val startStr = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(cal.time)

        val url = "https://connectapi.garmin.com/weight-service/weight/dateRange?startDate=$startStr&endDate=$endStr"

        fun executeRequest(token: String?): okhttp3.Response {
            val reqBuilder = Request.Builder().url(url)
            if (!token.isNullOrBlank()) {
                reqBuilder.header("Authorization", "Bearer $token")
                reqBuilder.header("Accept", "application/json")
                reqBuilder.header("User-Agent", "GCM-Android-5.0")
            } else if (!jwtWeb.isNullOrBlank()) {
                reqBuilder.header("Cookie", "JWT_WEB=$jwtWeb")
                reqBuilder.header("Accept", "application/json")
                reqBuilder.header("DI-Backend", "connectapi.garmin.com")
                reqBuilder.header("User-Agent", "Mozilla/5.0")
            } else {
                throw IllegalStateException("Nessun token di autenticazione Garmin disponibile")
            }
            return httpClient.newCall(reqBuilder.build()).execute()
        }

        var resp = executeRequest(diToken)

        // Silent automatic token refresh if token expired (401/403)
        if (resp.code == 401 || resp.code == 403) {
            if (refreshDiToken(context)) {
                diToken = GarminAuthManager.getDiToken(context)
                resp = executeRequest(diToken)
            }
        }

        if (resp.code == 401 || resp.code == 403) {
            GarminAuthManager.clear(context)
            throw IllegalStateException("Sessione Garmin scaduta. Effettua nuovamente l'accesso.")
        }
        if (!resp.isSuccessful) {
            throw IllegalStateException("Errore Garmin API (${resp.code})")
        }

        val rawBody = resp.body?.string() ?: "{}"
        val rawJson = JSONObject(rawBody)

        val entriesList = mutableListOf<JSONObject>()
        val dateWeightList = rawJson.optJSONArray("dateWeightList") ?: JSONArray()

        for (i in 0 until dateWeightList.length()) {
            val item = dateWeightList.getJSONObject(i)
            val parsed = parseEntry(item)
            if (parsed != null) {
                entriesList.add(parsed)
            }
        }

        // Sort by date ascending
        entriesList.sortBy { it.optString("timestamp") }

        // Compute moving averages & summary
        val processedEntries = computeMovingAverages(entriesList)
        val summary = computeSummary(processedEntries)

        val finalPayload = JSONObject()
        finalPayload.put("entries", JSONArray(processedEntries))
        finalPayload.put("summary", summary)

        val jsonString = finalPayload.toString()
        GarminAuthManager.saveCachedData(context, jsonString)
        return@withContext jsonString
    }

    private fun parseEntry(raw: JSONObject): JSONObject? {
        val rawDate = raw.optString("calendarDate", "").ifEmpty {
            raw.optString("date", "")
        }
        val timestampMs = raw.optLong("timestampGMT", 0L).let {
            if (it == 0L) raw.optLong("timestamp", 0L) else it
        }

        val dateStr: String
        val timeStr: String
        val timestampIso: String

        if (timestampMs > 0L) {
            val ms = if (timestampMs > 1e11) timestampMs else timestampMs * 1000L
            val d = Date(ms)
            dateStr = SimpleDateFormat("yyyy-MM-dd", Locale.US).format(d)
            timeStr = SimpleDateFormat("HH:mm:ss", Locale.US).format(d)
            timestampIso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US).format(d)
        } else if (rawDate.isNotEmpty()) {
            dateStr = rawDate.take(10)
            timeStr = if (rawDate.length > 10) rawDate.substring(11, minOf(19, rawDate.length)) else "08:00:00"
            timestampIso = "${dateStr}T$timeStr"
        } else {
            return null
        }

        if (!raw.has("weight")) return null
        val wRaw = raw.optDouble("weight")
        if (wRaw.isNaN() || wRaw <= 0.0) return null
        val weightKg = ((if (wRaw > 500.0) wRaw / 1000.0 else wRaw) * 100.0).roundToInt() / 100.0

        fun roundOpt(v: Double?, div: Double = 1.0): Double? {
            if (v == null || v.isNaN()) return null
            return ((v / div) * 100.0).roundToInt() / 100.0
        }

        val bmi = roundOpt(if (raw.has("bmi")) raw.optDouble("bmi") else null)
        val bodyFat = roundOpt(if (raw.has("bodyFat")) raw.optDouble("bodyFat") else null)
        val bodyWater = roundOpt(if (raw.has("bodyWater")) raw.optDouble("bodyWater") else null)
        val muscleRaw = if (raw.has("muscleMass")) raw.optDouble("muscleMass") else null
        val muscleMass = roundOpt(if (muscleRaw != null && muscleRaw > 200.0) muscleRaw / 1000.0 else muscleRaw)
        val boneRaw = if (raw.has("boneMass")) raw.optDouble("boneMass") else null
        val boneMass = roundOpt(if (boneRaw != null && boneRaw > 200.0) boneRaw / 1000.0 else boneRaw)
        val visceralFat = roundOpt(if (raw.has("visceralFat")) raw.optDouble("visceralFat") else null)
        val metabolicAge = roundOpt(if (raw.has("metabolicAge")) raw.optDouble("metabolicAge") else null)

        val obj = JSONObject()
        obj.put("timestamp", timestampIso)
        obj.put("date", dateStr)
        obj.put("time", timeStr)
        obj.put("weight_kg", weightKg)
        obj.put("weight_lbs", (weightKg * 2.20462 * 100.0).roundToInt() / 100.0)
        obj.put("bmi", bmi ?: JSONObject.NULL)
        obj.put("body_fat_pct", bodyFat ?: JSONObject.NULL)
        obj.put("body_water_pct", bodyWater ?: JSONObject.NULL)
        obj.put("bone_mass_kg", boneMass ?: JSONObject.NULL)
        obj.put("muscle_mass_kg", muscleMass ?: JSONObject.NULL)
        obj.put("visceral_fat", visceralFat ?: JSONObject.NULL)
        obj.put("metabolic_age", metabolicAge ?: JSONObject.NULL)
        return obj
    }

    private fun computeMovingAverages(entries: List<JSONObject>): List<JSONObject> {
        val n = entries.size
        for (i in 0 until n) {
            val currWeight = entries[i].getDouble("weight_kg")
            val prevWeight = if (i > 0) entries[i - 1].getDouble("weight_kg") else null
            entries[i].put("change_prev_kg", if (prevWeight != null) ((currWeight - prevWeight) * 100.0).roundToInt() / 100.0 else JSONObject.NULL)

            // 7d MA
            val window7 = entries.subList(maxOf(0, i - 6), i + 1).map { it.getDouble("weight_kg") }
            val ma7 = ((window7.sum() / window7.size) * 100.0).roundToInt() / 100.0
            entries[i].put("ma_7d", ma7)

            // 30d MA
            val window30 = entries.subList(maxOf(0, i - 29), i + 1).map { it.getDouble("weight_kg") }
            val ma30 = ((window30.sum() / window30.size) * 100.0).roundToInt() / 100.0
            entries[i].put("ma_30d", ma30)
        }
        return entries
    }

    private fun computeSummary(entries: List<JSONObject>): JSONObject {
        val s = JSONObject()
        if (entries.isEmpty()) {
            s.put("has_data", false)
            return s
        }

        val first = entries.first()
        val latest = entries.last()
        val weights = entries.map { it.getDouble("weight_kg") }

        val curW = latest.getDouble("weight_kg")
        val initW = first.getDouble("weight_kg")

        s.put("has_data", true)
        s.put("total_entries", entries.size)
        s.put("start_date", first.optString("date"))
        s.put("latest_date", latest.optString("date"))
        s.put("latest_time", latest.optString("time"))
        s.put("current_weight_kg", curW)
        s.put("current_weight_lbs", (curW * 2.20462 * 100.0).roundToInt() / 100.0)
        s.put("current_bmi", latest.opt("bmi"))
        s.put("current_body_fat", latest.opt("body_fat_pct"))
        s.put("current_muscle_mass", latest.opt("muscle_mass_kg"))
        s.put("current_body_water", latest.opt("body_water_pct"))
        s.put("total_change_kg", ((curW - initW) * 100.0).roundToInt() / 100.0)

        val diff7d = if (entries.size >= 7) curW - entries[entries.size - 7].getDouble("weight_kg") else curW - initW
        s.put("change_7d_kg", (diff7d * 100.0).roundToInt() / 100.0)

        val diff30d = if (entries.size >= 30) curW - entries[entries.size - 30].getDouble("weight_kg") else curW - initW
        s.put("change_30d_kg", (diff30d * 100.0).roundToInt() / 100.0)

        s.put("min_weight_kg", weights.minOrNull() ?: curW)
        s.put("max_weight_kg", weights.maxOrNull() ?: curW)
        s.put("avg_weight_kg", ((weights.sum() / weights.size) * 100.0).roundToInt() / 100.0)
        return s
    }
}
