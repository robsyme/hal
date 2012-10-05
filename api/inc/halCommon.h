/*
 * Copyright (C) 2012 by Glenn Hickey (hickey@soe.ucsc.edu)
 *
 * Released under the MIT license, see LICENSE.txt
 */

#ifndef _HALCOMMON_H
#define _HALCOMMON_H

#include <map>
#include <set>
#include <string>
#include <vector>
#include <locale>
#include <cassert>
#include <sstream>
#include "hal.h"

namespace hal {

inline bool compatibleWithVersion(const std::string& version)
{
  double myVersion, inVersion;
  // assume versions are strings tho we treat as floats for now.
  std::stringstream ss, ss2;
  ss << HAL_VERSION;
  ss >> myVersion;
  ss2 << version;
  ss2 >> inVersion;
  return (int)myVersion == (int)inVersion;
}

/** C++ style strtok-type function.  Can't remember why I wrote it */
std::vector<std::string> chopString(const std::string& inString,
                                    const std::string& separator);

/** Get the DNA reverse complement of a character.
 * If the input is not a nucleotide, then just return it as is
 * (ie no error checking) */
inline hal_dna_t reverseComplement(hal_dna_t c)
{
  switch (c)
  {
  case 'A' : return 'T'; 
  case 'a' : return 't'; 
  case 'C' : return 'G'; 
  case 'c' : return 'g';
  case 'G' : return 'C';
  case 'g' : return 'c';
  case 'T' : return 'A';
  case 't' : return 'a';
  default : break;
  }
  return c;
}

/** Check if a DNA character is a valid base (or n-chracter) */
inline hal_bool_t isNucleotide(hal_dna_t c)
{
  hal_bool_t result = false;
  switch (c)
  {
  case 'A' : 
  case 'a' : 
  case 'C' : 
  case 'c' : 
  case 'G' : 
  case 'g' : 
  case 'T' : 
  case 't' : 
  case 'N' :
  case 'n' :
    result = true;
  default : break;
  }
  return result;
}

/** Count the mutations between two DNA strings */
inline hal_size_t hammingDistance(const std::string& s1, const std::string& s2)
{
  assert(s1.length() == s2.length());
  hal_size_t dist = 0;
  for (size_t i = 0; i < s1.length(); ++i)
  {
    if (std::toupper(s1[i]) != std::toupper(s2[i]))
    {
      ++dist;
    }
  }
  return dist;
}

/* Given a set of genomes (input set) return all genomes in the spanning
 * tree (root should be the root of the alignment */
size_t getGenomesInSpanningTree(const Genome* root, 
                                const std::set<const Genome*>& inputSet,
                                std::set<const Genome*>& outputSet);

/** keep track of bases by storing 2d intervals 
 * For example, if we want to flag positions in a genome
 * that we have visited, this structure will be fairly 
 * efficient provided positions are clustered into intervals */
class PositionCache
{
public:
   PositionCache() : _size(0) {}
   bool insert(hal_index_t pos);
   bool find(hal_index_t pos) const;
   void clear();
   bool check() const;
   hal_size_t size() const { return _size; }
   hal_size_t numIntervals() const { return _set.size(); }
protected:
   // sorted by last index, so each interval is (last, first)
   typedef std::map<hal_index_t, hal_index_t> IntervalSet;
   IntervalSet _set;
   hal_size_t _size;
};

}

#endif

