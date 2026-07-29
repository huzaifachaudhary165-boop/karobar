# ML Kit text recognition ships one artifact per script. The plugin's Java code
# references all of them, but we depend only on the Latin recogniser — the one
# `BillReader` actually asks for — so the others are genuinely absent and R8
# stops the build over it.
#
# Silencing them is the correct fix: pulling in Chinese, Japanese, Korean and
# Devanagari models would add tens of megabytes to the APK to satisfy code paths
# that can never run. If a Devanagari-script bill ever needs reading, add that
# dependency deliberately and update BillReader's script at the same time.
-dontwarn com.google.mlkit.vision.text.chinese.**
-dontwarn com.google.mlkit.vision.text.devanagari.**
-dontwarn com.google.mlkit.vision.text.japanese.**
-dontwarn com.google.mlkit.vision.text.korean.**

# The barcode scanner and text recogniser both load native models by reflection.
-keep class com.google.mlkit.** { *; }
-keep class com.google.android.gms.internal.mlkit_** { *; }

# Google Sign-In reads these off the wire into typed objects by reflection.
-keep class com.google.android.gms.auth.api.signin.** { *; }
-keep class com.google.android.gms.common.api.** { *; }

# Flutter's deferred-component machinery, referenced only from generated code.
-dontwarn io.flutter.embedding.engine.deferredcomponents.**
