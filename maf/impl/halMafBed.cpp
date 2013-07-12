/*
 * Copyright (C) 2013 by Glenn Hickey (hickey@soe.ucsc.edu)
 *
 * Released under the MIT license, see LICENSE.txt
 */

#include <deque>
#include <cassert>
#include "halMafBed.h"

using namespace std;
using namespace hal;

MafBed::MafBed(std::ostream& mafStream, AlignmentConstPtr alignment,
               const Genome* refGenome, const Sequence* refSequence,
               std::set<const Genome*>& targetSet,
               MafExport& mafExport) :
  BedScanner(),
  _mafStream(mafStream),
  _alignment(alignment),
  _refGenome(refGenome),
  _refSequence(refSequence),
  _targetSet(targetSet),
  _mafExport(mafExport)
{

}
   
MafBed::~MafBed()
{

}

void MafBed::visitLine()
{
  const Sequence* refSequence = _refGenome->getSequence(_bedLine._chrName);
  if (refSequence != NULL && 
      (_refSequence == NULL || refSequence == _refSequence))
  {
    if (_bedVersion <= 9)
    {
      if (_bedLine._end <= _bedLine._start ||
          _bedLine._end > (hal_index_t)refSequence->getSequenceLength())
      {
        cerr << "Line " << _lineNumber << ": BED coordinates invalid\n";
      }
      else
      {
        _mafExport.convertSegmentedSequence(_mafStream, _alignment, 
                                            refSequence, 
                                            _bedLine._start, 
                                            _bedLine._end - _bedLine._start, 
                                            _targetSet);
      }
    }
    else
    {
      for (size_t i = 0; i < _bedLine._blocks.size(); ++i)
      {
        if (_bedLine._blocks[i]._length == 0 ||
            _bedLine._blocks[i]._start + _bedLine._blocks[i]._length >= 
            (hal_index_t)refSequence->getSequenceLength())
        {
          cerr << "Line " << _lineNumber << ", block " << i 
               <<": BED coordinates invalid\n";
        }
        else
        {
          _mafExport.convertSegmentedSequence(_mafStream, _alignment, 
                                              refSequence, 
                                              _bedLine._blocks[i]._start,
                                              _bedLine._blocks[i]._length,
                                              _targetSet);
        }
      }
    }
  }
  else if (_refSequence == NULL)
  {
    cerr << "Line " << _lineNumber << ": BED sequence " << _bedLine._chrName
         << " not found in genome " << _refGenome->getName() << '\n';
  }
}
