import 'package:flutter/material.dart';

/// Visual rules, all driven by where this runs: a tablet held at arm's length
/// in a room with one window and a flickering bulb, used by someone standing
/// up between patients.
class AppTheme {
  /// Minimum tap target. Material's 48dp is too small for a gloved hand.
  static const double touchTarget = 64;

  /// Body text. Deliberately larger than Material's default 14sp.
  static const double bodySize = 18;
  static const double titleSize = 24;

  static const Color danger = Color(0xFFC62828);
  static const Color dangerSurface = Color(0xFFFFEBEE);
  static const Color warning = Color(0xFFE65100);
  static const Color success = Color(0xFF2E7D32);
  static const Color offline = Color(0xFF616161);

  static ThemeData light() {
    final ColorScheme scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF00695C),
      brightness: Brightness.light,
      // High contrast: clinic lighting is bad and screens get dusty.
      contrastLevel: 0.5,
    );
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      // Not `comfortable`: it subtracts 4dp from every button and
      // silently breaks the 64dp touch target this app promises.
      visualDensity: VisualDensity.standard,
      textTheme: const TextTheme(
        bodyMedium: TextStyle(fontSize: bodySize),
        bodyLarge: TextStyle(fontSize: bodySize + 2),
        titleLarge: TextStyle(fontSize: titleSize, fontWeight: FontWeight.w600),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          minimumSize: const Size(double.infinity, touchTarget),
          textStyle:
              const TextStyle(fontSize: bodySize, fontWeight: FontWeight.w600),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(double.infinity, touchTarget),
          textStyle: const TextStyle(fontSize: bodySize),
        ),
      ),
      inputDecorationTheme: const InputDecorationTheme(
        border: OutlineInputBorder(),
        contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 20),
      ),
      chipTheme: const ChipThemeData(
        padding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
        labelStyle: TextStyle(fontSize: bodySize),
      ),
    );
  }
}
