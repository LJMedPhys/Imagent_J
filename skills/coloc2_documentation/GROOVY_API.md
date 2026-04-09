# Coloc 2 Groovy API Guide

### Execution Command
`IJ.run("Coloc 2", "parameter_string")`

### Verified Parameters
| Argument | Type | Description |
|:---|:---|:---|
| `channel_1` | String | Title of the first image (use brackets `[]` if name has spaces). |
| `channel_2` | String | Title of the second image. |
| `roi_or_mask` | String | Omit the argument, when no roi_or_mask is present|
| `threshold_regression` | String | Use `Costes` (default), `Bisections`, or `None`. |
| `display_images` | Boolean | If `true`, opens PDF-style result images and scatterplots. |
| `display_results` | Boolean | If `true`, populates the Log and Results Table. |
| `statistic_1` | Boolean | Pearson's R (Recommended: `true`). |
| `statistic_2` | Boolean | Manders' M1/M2 (Recommended: `true`). |
| `statistic_3` | Boolean | Costes' P-Value (Significance test). |
| `statistic_4` | Boolean | Li's ICQ. |
| `statistic_5` | Boolean | Spearman's rank correlation. |
| `number_of_iterations` | Integer | Iterations for Costes test (Recommended: `100`). |
| `psf_width` | Float | PSF size in pixels. Usually `3.0`. |

### Crucial Syntax Rules
1. **No Spaces:** Do not put spaces around the `=` sign (e.g., `channel_1=C1` is correct; `channel_1 = C1` will fail).
2. **Brackets:** Wrap image names in brackets if they contain spaces: `channel_1=[Result of C1]`.
3. **Headless Mode:** Set `display_images=false` when running on a server or in a loop to prevent UI hang.