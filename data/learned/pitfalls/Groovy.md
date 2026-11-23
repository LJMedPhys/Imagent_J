<!--p:f8078f4f seen:1 lang:Groovy type:Logic class:ij.io.TiffDecoder scope:general kw:outofmemoryerror,tiffdecoder,fileinfo,opener.openimage,representative slice,full stack load,tiff metadata,large volume-->
- Avoid OutOfMemoryError by reading TIFF metadata with TiffDecoder and opening only one representative slice instead of loading both full volumes.
    fi647 = readFileInfo(path647)
    fiDapi = readFileInfo(pathDapi)
    repSource = new Opener().openImage(path647, 1)
    ImageProcessor downsampledIp = repSource.getProcessor().duplicate().resize(dsW, dsH, true)
<!--p:7b32466b seen:1 lang:Groovy type:Logic class:ij.IJ scope:general kw:stardist,ij.getimage,imageplus,dataset,imagejfunctions,batch-safe,headless,uiservice-->
- Replace UI-dependent IJ.getImage retrieval with direct StarDist output conversion to ImagePlus for batch-safe execution.
    if (labelOutput instanceof ImagePlus) {
        labelImp = (ImagePlus) labelOutput
    } else if (labelOutput instanceof Dataset) {
        labelImp = ImageJFunctions.wrap(((Dataset) labelOutput).getImgPlus(), cropId + '_labels')
    } else {
        throw new IllegalStateException('VERIFICATION FAILED: Unsupported StarDist label output type for ' + cropId + ': ' + labelOutput.getClass().getName())
    }
<!--p:f02988f3 seen:1 lang:Groovy type:Logic class:ImagePlus scope:general kw:groovy variable redeclaration,script scope variable,duplicate local variable,loop declaration error,imageplus duplicate,groovy compilation,assignment inside loop-->
- Avoid redeclaring a script-scope Groovy variable inside a loop; assign the duplicate image to the existing variable.
    imp2 = sourceCh00.duplicate()

