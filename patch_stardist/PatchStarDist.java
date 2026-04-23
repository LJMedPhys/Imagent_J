import javassist.*;
import java.io.*;
import java.nio.file.*;
import java.util.zip.*;

/**
 * Patches TrackMate-StarDist 2.0.0 to fix ClassCastException in setSettings()
 * and getDetector() when TARGET_CHANNEL is deserialized from XML as a String.
 *
 * Fix: insertBefore in both methods to convert String→Integer before the
 * existing (Integer) cast executes.
 *
 * Also updates the JAR in-place via java.util.zip (avoids needing the 'zip'
 * CLI tool which is not installed in the base Docker image).
 */
public class PatchStarDist {

    static final String FIJI_JARS = "/opt/Fiji.app/jars";
    static final String JAR       = FIJI_JARS + "/TrackMate-StarDist-2.0.0.jar";
    static final String OUT_DIR   = "/tmp/stardist-patched-classes";

    // Injected at top of setSettings(Map settings) — $1 = settings
    static final String FIX_PANEL =
        "{ Object _v = $1.get(\"TARGET_CHANNEL\");" +
        "  if (_v != null && !(_v instanceof Integer))" +
        "    $1.put(\"TARGET_CHANNEL\", Integer.valueOf(_v.toString())); }";

    // Injected at top of getDetector(img, settings, interval, frame) — $2 = settings
    static final String FIX_FACTORY =
        "{ Object _v = $2.get(\"TARGET_CHANNEL\");" +
        "  if (_v != null && !(_v instanceof Integer))" +
        "    $2.put(\"TARGET_CHANNEL\", Integer.valueOf(_v.toString())); }";

    public static void main(String[] args) throws Exception {
        new File(OUT_DIR).mkdirs();

        // ── Build classpath from all Fiji JARs ─────────────────────────────
        ClassPool pool = new ClassPool(ClassPool.getDefault());
        Files.walk(Paths.get(FIJI_JARS))
             .filter(p -> p.toString().endsWith(".jar"))
             .forEach(p -> {
                 try { pool.appendClassPath(p.toString()); }
                 catch (Exception e) { /* skip unreadable JARs */ }
             });
        pool.appendClassPath(JAR);

        // ── Patch 1: StarDistDetectorConfigurationPanel.setSettings ────────
        CtClass panel = pool.get(
            "fiji.plugin.trackmate.stardist.StarDistDetectorConfigurationPanel");
        CtMethod[] ssMethods = panel.getDeclaredMethods("setSettings");
        if (ssMethods.length == 0) {
            System.err.println("[patch] ERROR: setSettings not found in ConfigPanel");
            System.exit(1);
        }
        ssMethods[0].insertBefore(FIX_PANEL);
        panel.writeFile(OUT_DIR);
        System.out.println("[patch] StarDistDetectorConfigurationPanel.setSettings patched");

        // ── Patch 2: StarDistDetectorFactory.getDetector ───────────────────
        CtClass factory = pool.get(
            "fiji.plugin.trackmate.stardist.StarDistDetectorFactory");
        CtMethod[] gdMethods = factory.getDeclaredMethods("getDetector");
        if (gdMethods.length == 0) {
            System.err.println("[patch] ERROR: getDetector not found in Factory");
            System.exit(1);
        }
        gdMethods[0].insertBefore(FIX_FACTORY);
        factory.writeFile(OUT_DIR);
        System.out.println("[patch] StarDistDetectorFactory.getDetector patched");

        // ── Update the JAR in-place ─────────────────────────────────────────
        // Replace only the two patched entries; copy all others unchanged.
        String tmpJar = JAR + ".patching";
        try (ZipInputStream  zin  = new ZipInputStream(new FileInputStream(JAR));
             ZipOutputStream zout = new ZipOutputStream(new FileOutputStream(tmpJar))) {

            ZipEntry entry;
            while ((entry = zin.getNextEntry()) != null) {
                File patched = new File(OUT_DIR, entry.getName());
                ZipEntry outEntry = new ZipEntry(entry.getName());
                zout.putNextEntry(outEntry);
                if (patched.exists() && patched.isFile()) {
                    System.out.println("[patch] Replacing in JAR: " + entry.getName());
                    Files.copy(patched.toPath(), zout);
                } else {
                    zin.transferTo(zout);
                }
                zout.closeEntry();
                zin.closeEntry();
            }
        }
        Files.move(Paths.get(tmpJar), Paths.get(JAR),
                   java.nio.file.StandardCopyOption.REPLACE_EXISTING);
        System.out.println("[patch] TrackMate-StarDist-2.0.0.jar updated successfully");
    }
}
