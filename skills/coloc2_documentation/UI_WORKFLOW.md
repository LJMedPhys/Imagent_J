# Coloc 2 UI Sample Workflow

### Standard Validation Procedure
1. **Open Image:** Load a two-channel image (e.g., `File > Open Samples > HeLa Cells`).
2. **Split:** `Image > Color > Split Channels`.
3. **Open Coloc 2:** `Analyze > Colocalization > Coloc 2`.
4. **Selection:**
   - Channel 1: `C1-HeLa.tif`
   - Channel 2: `C2-HeLa.tif`
5. **Config:** Keep default statistics checked. Set `Iterations` to `50` for a balance of speed and accuracy.
6. **Execution:** Click **OK**.
7. **Verification:**
   - Check the **Log** window.
   - **PCC (Pearson):** Should be > 0.5 for moderate colocalization.
   - **Costes P-Value:** If this is **1.00** (or > 0.95), the result is statistically valid. If it is low, the colocalization observed may be due to random pixel distribution.