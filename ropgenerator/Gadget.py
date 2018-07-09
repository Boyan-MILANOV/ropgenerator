# -*- coding: utf-8 -*- 
# Gadget module: model a whole gadget object

from ropgenerator.Graph import REILtoGraph, Graph, GraphException
from ropgenerator.Semantics import Semantics 
from ropgenerator.Expressions import SSAExpr, SSAReg, MEMExpr, Expr
import ropgenerator.Architecture as Arch

from enum import Enum

class GadgetException(Exception):
    """
    Custom Exception type for this module
    """
    def __init__(self, msg):
        self.msg = msg
        
    def __str__(self):
        return self.msg

################################
# USEFUL TYPES AND DEFINITIONS #
################################
class GadgetType(Enum):
    REGULAR = "REGULAR"
    INT80 = "INT 0x80"
    SYSCALL = "SYSCALL"

class RetType(Enum):
    UNKNOWN = "UNKWNOWN"
    RET = "RET"
    JMP = "JMP"
    CALL = "CALL"

################
# GADGET CLASS #
################

class Gadget:
    def __init__(self, addr_list, raw):
        """
        addr_list = list of addresses of the gadget (if duplicate gadgets)
        raw = raw string of gadget asm 
        """
        # Check the type of the gadget 
        # Check for 'int 0x80' gadgets
        if( raw == '\xcd\x80' and Arch.currentIsIntel()): 
            self.type = GadgetType.INT80
            self.asmStr = 'int 0x80'
            self.hexStr = '\\xcd\\x80'
            self.addrList = addr_list
            self.semantics = Semantics() 
            return 
        # Check for 'syscall' gadgets 
        elif( raw == '\x0f\x05' and Arch.currentIsIntel()):
            self.type = GadgetType.SYSCALL
            self.asmStr = 'syscall'
            self.hexStr = '\\x0f\\x05'
            self.addrList = addr_list
            self.semantics = Semantics()
            return 
        
        # Translate raw assembly into REIL 
        # Then compute the Graph and its semantics 
        try:
            (irsb, ins) = Arch.currentArch.asmToREIL(raw)
        except Arch.ArchException as e:
            raise GadgetException(str(e))
        try: 
            self.graph = REILtoGraph(irsb)
            self.semantics = self.graph.getSemantics()
        except Exception as e:
            raise GadgetException(str(e))
        
        self.type = GadgetType.REGULAR
        # Possible addresses     
        self.addrList = addr_list
        # String representations
        self.asmStr = '; '.join(str(i) for i in ins) 
        self.hexStr = '\\x' + '\\x'.join("{:02x}".format(ord(c)) for c in raw)
        # Length of the gadget 
        self.nbInstr = len(ins)
        self.nbInstrREIL = len(irsb)
        
        # List of modified registers 
        self._modifiedRegs = []
        for reg in self.semantics.registers.keys():
            if (reg.ind and (SSAExpr(reg) != self.semantics.registers[reg][0].expr) ):
                self._modifiedRegs.append(reg.num)
        self._modifiedRegs = list(set(self._modifiedRegs))
        
        # SP Increment 
        if( self.type != GadgetType.REGULAR ):
            self.spInc = None
        else:
            sp_num = Arch.n2r(Arch.currentArch.sp)
            if( not sp_num in self.graph.lastMod ):
                self.spInc = 0
            else:                
                sp = SSAReg(sp_num, self.graph.lastMod[sp_num])
                if( len(self.semantics.get(sp)) == 1 ):
                    (isInc, inc) = self.semantics.get(sp)[0].expr.isRegIncrement(sp_num)
                    if( isInc ):
                        self.spInc = inc
                    else:
                        self.spInc = None
                else:
                    self.spInc = None
        
        # Return type
        self.retType = RetType.UNKNOWN
        self.retValue = None
        if( self.type == GadgetType.REGULAR ):
            ip_num = Arch.n2r(Arch.currentArch.ip)
            ip = SSAReg(ip_num, self.graph.lastMod[ip_num])
            sp_num = Arch.n2r(Arch.currentArch.sp)
            
            if( self.spInc != None ):
                for p in self.semantics.get(ip):
                    if( p.cond.isTrue()):
                        if( isinstance(p.expr, MEMExpr)):
                            addr = p.expr.addr
                            (isInc, inc) = addr.isRegIncrement(sp_num)    
                            # Normal ret if the final value of the IP is value that was in memory before the last modification of SP ( i.e final_IP = MEM[final_sp - size_of_a_register )        
                            if( isInc and inc == (self.spInc - (Arch.currentArch.octets)) ):
                                self.retType = RetType.RET
                                self.retValue = p.expr
                        elif( isinstance(p.expr, SSAExpr )):
                            self.retValue = p.expr
                            # Try to detect gadgets ending by 'call' 
                            if( self.ins[-1]._mnemonic[:4] == "call"):
                                self.retType = RetType.CALL
                            else:
                                self.retType = RetType.JMP
    
    # Accessors and useful functions
    def __str__(self):
        return self.asmStr
    
    def modifiedRegs(self):
        return self._modifiedRegs
        
    def memoryWrites(self):
        return self.semantics.memory.keys()
        
    def getSemantics(self, value):
        if( isinstance( value, Expr)):
            return self.semantics.get(value)
        else:
            # Try to translate into a reg 
            if( isinstance(value, int)):
                num = value
            elif( value in Arch.regNameToNum ):
                num = Arch.n2r(value)
            else:
                return []
            # Return corresponding if present 
            if( num in self.graph.lastMod ):
                reg = SSAReg(num, self.graph.lastMod[num])
                return self.semantics.get(reg)
            # Or return nothing 
            else:
                return SSAExpr(num, 0)