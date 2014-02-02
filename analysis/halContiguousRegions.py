#!/usr/bin/env python
# won't work in the general case right now
# (i.e. needs to be positive query strand)
import sys
import os
import argparse
import itertools
from sonLib import bioio
from sonLib.bioio import getTempFile
from operator import itemgetter
from collections import defaultdict
from jobTree.scriptTree.target import Target
from jobTree.scriptTree.stack import Stack
from sonLib.bioio import logger
from sonLib.bioio import setLoggingFromOptions

# Useful itertools recipe
def pairwise(iterable):
    "s -> (s0,s1), (s1,s2), (s2, s3), ..."
    a, b = itertools.tee(iterable)
    next(b, None)
    return itertools.izip(a, b)

class Setup(Target):
    def __init__(self, args):
        Target.__init__(self)
        self.args = args

    def run(self):
        numLines = self.numLinesInFile(self.args.bedFile)
        slices = []
        sliceNum = self.args.sliceNum
        if numLines > self.args.sliceNum:
            step = numLines/self.args.sliceNum
            count = 0
            for i in xrange(sliceNum):
                slices.append((count, count + step))
                count += step
            slices[-1] = (slices[-1][0], slices[-1][1] + numLines % self.args.sliceNum)
        else:
            sliceNum = numLines
            slices = [[0, numLines]]

        sliceOutputs = []
        for i in xrange(sliceNum):
            slice = slices[i]
            sliceOut = getTempFile(rootDir=self.getGlobalTempDir())
            sliceOutputs.append(sliceOut)
            self.addChildTarget(RunContiguousRegions(self.args, slice,
                                                     sliceOut))
        self.setFollowOnTarget(WriteToOutput(self.args, sliceOutputs))

    def numLinesInFile(self, fileName):
        n = 0
        for line in open(fileName):
            n += 1
        return n

class RunContiguousRegions(Target):
    def __init__(self, args, slice, sliceOut):
        Target.__init__(self)
        self.args = args
        self.slice = slice
        self.sliceOut = sliceOut

    def run(self):
        contiguousRegions = ContiguousRegions(self.args.alignment,
                                              self.args.srcGenome,
                                              self.args.destGenome,
                                              self.args.maxGap,
                                              self.getGlobalTempDir(),
                                              self.args.maxIntronDiff,
                                              self.args.deletionGaps,
                                              self.args.requiredMapFraction)
        startLineNum = self.slice[0]
        endLineNum = self.slice[1]
        outFile = open(self.sliceOut, 'w')
        for (line, numBases) in contiguousRegions.getContiguousLines(self.args.bedFile,
                                                         startLineNum,
                                                         endLineNum):
            if self.args.printNumAdjacencies:
                outFile.write("%d\n" % numBases)
            else:
                outFile.write(line)

class WriteToOutput(Target):
    def __init__(self, args, sliceFiles):
        Target.__init__(self)
        self.args = args
        self.sliceFiles = sliceFiles

    def run(self):
        outFile = open(self.args.outFile, 'w')
        for filename in self.sliceFiles:
            for line in open(filename):
                outFile.write(line)

class ContiguousRegions:
    def __init__(self, alignment, srcGenome, destGenome, maxGap, tempRoot,
                 maxIntronDiff, noDeletions, requiredMapFraction):
        self.alignment = alignment
        self.srcGenome = srcGenome
        self.destGenome = destGenome
        self.maxGap = maxGap
        self.tempRoot = tempRoot
        self.maxIntronDiff = maxIntronDiff
        self.noDeletions = noDeletions
        self.requiredMapFraction = requiredMapFraction

    def liftover(self, bedLine):
        """Lift a bedLine over to the target genome, parse the PSL output, and
        return a map from target sequence -> [(query block, [target
        block(s)])]

        Blocks are (start, end, strand) where start < end

        """
        tempSrc = getTempFile("ContiguousRegions.tempSrc.bed",
                                    rootDir=self.tempRoot)
        tempDest = getTempFile("ContiguousRegions.tempDest.psl",
                                     rootDir=self.tempRoot)
        open(tempSrc, 'w').write("%s\n" % bedLine)
        cmd = "halLiftover --outPSL %s %s %s %s %s" % (self.alignment,
                                                       self.srcGenome,
                                                       tempSrc,
                                                       self.destGenome,
                                                       tempDest)
        bioio.system(cmd)
        pslLines = open(tempDest).read().split("\n")
        os.remove(tempSrc)
        os.remove(tempDest)
        pslLines = map(lambda x: x.split(), pslLines)
        # Get target blocks for every query block. All adjacencies
        # within a block are by definition preserved. Adjacencies
        # between target blocks (and query blocks with the commandline
        # option) are what determine if the structure is preserved.
        # dict is to keep blocks separated by target sequence & strand
        blocks = defaultdict(list)
        for pslLine in pslLines:
            if pslLine == []:
                continue
            qStrand = pslLine[8][0]
            assert(qStrand == '+')
            if len(pslLine[8]) != 1:
                assert(len(pslLine[8]) == 2)
                tStrand = pslLine[8][1]
            else:
                tStrand = '+'
            tName = pslLine[13]
            tSize = int(pslLine[14])
            blockSizes = [int(i) for i in pslLine[18].split(",") if i != '']
            qStarts = [int(i) for i in pslLine[19].split(",") if i != '']
            tStarts = [int(i) for i in pslLine[20].split(",") if i != '']
            assert(len(blockSizes) == len(qStarts) and
                   len(qStarts) == len(tStarts))
            for blockLen, qStart, tStart in zip(blockSizes, qStarts, tStarts):
                qBlock = (qStart, qStart + blockLen, qStrand)
                tBlock = (tStart, tStart + blockLen, tStrand) if tStrand == '+' else (tSize - tStart - blockLen, tSize - tStart, tStrand)
                blocks[tName].append((qBlock, tBlock))

        # Sort & merge query blocks in cases of duplication
        return self.mergeBlocks(blocks)

    def mergeBlocks(self, blockDict):
        """Take a dict of lists of (query block, target block) and turn it
        into a dict of lists of (query block, [target block(s)]),
        sorted by query block start.
        """
        def takeFirst(len, block):
            if block[2] == '+':
                return (block[0], block[0] + len, block[2])
            else:
                return (block[1] - len, block[1], block[2])
        def takeLast(len, block):
            if block[2] == '+':
                return (block[1] - len, block[1], block[2])
            else:
                return (block[0], block[0] + len, block[2])

        ret = {}
        for seq, blockList in blockDict.items():
            blockList.sort(key=itemgetter(0))
            newBlockList = []
            prev = None
            for blocks in blockList:
                if prev is not None:
                    qBlock = blocks[0]
                    qStrand = qBlock[2]
                    assert(qStrand == '+')
                    tBlock = blocks[1]
                    tStrand = tBlock[2]
                    prevqBlock = prev[0]
                    prevqStrand = prevqBlock[2]
                    assert(prevqStrand == '+')
                    prevtBlocks = prev[1]
                    if qBlock[0] < prevqBlock[1]:
                        # overlapping query block
                        assert(qBlock[0] >= prevqBlock[0])
                        preOverlapSize = qBlock[0] - prevqBlock[0]
                        postOverlapSize = abs(qBlock[1] - prevqBlock[1])
                        if qBlock[0] > prevqBlock[0]:
                            # block before overlap
                            preOverlapqBlock = (prevqBlock[0], qBlock[0], prevqStrand)
                            preOverlaptBlocks = [takeFirst(preOverlapSize, x) for x in prevtBlocks]
                            newBlockList[-1] = (preOverlapqBlock, preOverlaptBlocks)
                        elif qBlock[0] == prevqBlock[0]:
                            newBlockList = newBlockList[:-1]
                        # overlapping block
                        overlapSize = abs(min(qBlock[1], prevqBlock[1]) - qBlock[0])
                        if qBlock[1] > prevqBlock[1]:
                            overlapqBlock = (qBlock[0], qBlock[1] - postOverlapSize, qStrand)
                            overlaptBlocks = [takeLast(overlapSize, x) for x in prevtBlocks] + [takeLast(overlapSize, takeFirst(overlapSize, tBlock))]
                            newBlockList.append((overlapqBlock, overlaptBlocks))
                        else:
                            overlapqBlock = (qBlock[0], prevqBlock[1] - postOverlapSize, qStrand)
                            overlaptBlocks = [takeLast(overlapSize, takeFirst(preOverlapSize + overlapSize, x)) for x in prevtBlocks] + [tBlock]
                            newBlockList.append((overlapqBlock, overlaptBlocks))
                        if qBlock[1] > prevqBlock[1]:
                            # block after overlap
                            postOverlapqBlock = (prevqBlock[1], qBlock[1], qStrand)
                            postOverlaptBlocks = [takeLast(postOverlapSize, tBlock)]
                            newBlockList.append((postOverlapqBlock, postOverlaptBlocks))
                        elif qBlock[1] < prevqBlock[1]:
                            # block after overlap
                            postOverlapqBlock = (qBlock[1], prevqBlock[1], qStrand)
                            postOverlaptBlocks = [takeLast(postOverlapSize, x) for x in prevtBlocks]
                            newBlockList.append((postOverlapqBlock, postOverlaptBlocks))
                    else:
                        # No overlap
                        newBlockList.append((qBlock, [tBlock]))
                else:
                    # sloppy
                    newBlockList.append((blocks[0], [blocks[1]]))
                prev = newBlockList[-1]
            ret[seq] = newBlockList
        return ret

    def isPreserved(self, blocks1, blocks2):
        """Check if any possible adjacency between the target blocks is
           preserved. Query start for blocks1 should be less than or
           equal to query start for blocks2.
        """
        for x, y in itertools.product(blocks1, blocks2):
            if x[2] == y[2]: # orientation preserved
                if x[2] == '+' and y[0] - x[1] in xrange(0, 100):
                    return True
                elif x[2] == '-' and x[0] - y[1] in xrange(0, 100):
                    return True
        return False

    def isContiguousInTarget(self, bedLine):
        elementIsPreserved = False
        blockDict = self.liftover(bedLine)
        if blockDict is None:
            return (False, 0)

        bedFields = bedLine.split()
        bedStart = int(bedFields[1])
        bedEnd = int(bedFields[2])
        bedIntrons = []
        bedLength = 0
        if len(bedFields) == 12:
            blockStarts = map(int, bedFields[11].split(","))
            blockSizes = map(int, bedFields[10].split(","))
            assert(len(blockStarts) == len(blockSizes))
            bedBlocks = [(bedStart + start, bedStart + start + size)
                         for start, size in zip(blockStarts, blockSizes)]
            prevEnd = None
            for block in bedBlocks:
                if prevEnd is not None:
                    gap = block[0] - prevEnd
                    assert(gap >= 0)
                    bedIntrons.append((prevEnd, block[0]))
                prevEnd = block[1]
            bedLength = sum(blockSizes)
        else:
            bedLength = bedEnd - bedStart

        numPreservedAdjacencies = 0

        # take only the blocks from the target sequence with the most mapped
        # bases
        tSeqMapped = {}
        for seq, value in blockDict.items():
            qBlocks = map(itemgetter(0), value)
            mappedBases = reduce(lambda r, v: r + (v[1] - v[0]), qBlocks, 0)
            # Adjacencies within blocks are always preserved.
            numPreservedAdjacencies += mappedBases - len(qBlocks)
            mappedFraction = float(mappedBases)/bedLength
            tSeqMapped[seq] = mappedFraction
        if len(tSeqMapped) == 0:
            # can happen if the sequence doesn't map to the target at all
            return (False, 0)

        for seq, blocks in blockDict.items():
            # FIXME: Need to account for introns again
            # And qGaps if option is given
            preservedForSeq = True
            if tSeqMapped[seq] < self.requiredMapFraction:
                preservedForSeq = False
            tBlocks = map(itemgetter(1), blocks)
            for x, y in pairwise(tBlocks):
                if self.isPreserved(x, y):
                    numPreservedAdjacencies += 1
                else:
                    preservedForSeq = False
            if preservedForSeq:
                elementIsPreserved = True

        return (elementIsPreserved, numPreservedAdjacencies)

    def getContiguousLines(self, bedPath, startLineNum=0, endLineNum=-1):
        for lineNum, line in enumerate(open(bedPath)):
            if lineNum < startLineNum:
                continue
            elif lineNum >= endLineNum:
                break

            (metCriteria, numAdjacencies) = self.isContiguousInTarget(line)
            if metCriteria:
                yield (line, numAdjacencies)
            
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("alignment", help="HAL alignment file")
    parser.add_argument("srcGenome", help="Reference genome")
    parser.add_argument("bedFile", help="Bed file (in ref coordinates)")
    parser.add_argument("destGenome", help="Genome to check contiguity in")
    parser.add_argument("outFile", help="Output BED file")
    parser.add_argument("--maxGap", help="maximum gap size to accept", 
                        default=100, type=int)
    parser.add_argument("--deletionGaps", help="care about deletion gaps",
                        default=False, action='store_true')
    parser.add_argument("--sliceNum", help="number of slices to create",
                        type=int, default=1)
    parser.add_argument("--maxIntronDiff", help="Maximum number of bases "
                        "that intron gaps are allowed to change by", type=int,
                        default=10000)
    parser.add_argument("--requiredMapFraction", help="Fraction of bases in "
                        "the query that need to map to the target to be "
                        "accepted", type=float, default=0.0)
    parser.add_argument("--printNumAdjacencies", help="instead of printing the "
                        "passing BED lines, print the number of adjacencies "
                        "that passed", action='store_true', default=False)
    # TODO: option to allow dupes in the target
    Stack.addJobTreeOptions(parser)
    args = parser.parse_args()
    setLoggingFromOptions(args)
    result = Stack(Setup(args)).startJobTree(args)
    if result:
        raise RuntimeError("Jobtree has failed jobs.")

    return 0
    
if __name__ == '__main__':
    from hal.analysis.halContiguousRegions import *
    sys.exit(main())